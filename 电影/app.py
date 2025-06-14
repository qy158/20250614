from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from sqlalchemy import UniqueConstraint

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-should-be-changed-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:12345678@localhost/movies_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['ALLOWED_EXTENSIONS'] = {'zip'}  # 只允许ZIP格式

# 确保上传目录存在
upload_folder = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'])
os.makedirs(upload_folder, exist_ok=True)

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


# 用户模型
class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# 电影模型（关键修改：修改 ratings 关系的 backref 名称）
class Movie(db.Model):
    __tablename__ = 'movie'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    director = db.Column(db.String(100))
    genre = db.Column(db.String(50))
    cover_image = db.Column(db.String(100))
    file_path = db.Column(db.String(200))  # 存储相对路径
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='uploaded_movies')
    comments = db.relationship('Comment', backref='movie', lazy=True)
    ratings = db.relationship('Rating', backref='rated_movie', lazy=True)  # 改为 backref='rated_movie'

    @property
    def average_rating(self):
        if not self.ratings:
            return 0
        return sum(r.rating for r in self.ratings) / len(self.ratings)


# 评论模型
class Comment(db.Model):
    __tablename__ = 'comment'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    user = db.relationship('User', backref='user_comments')


# 评分模型
class Rating(db.Model):
    __tablename__ = 'rating'
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)

    # 唯一约束：用户对电影的评分唯一
    __table_args__ = (
        UniqueConstraint('user_id', 'movie_id', name='uq_user_movie_rating'),
    )

    user = db.relationship('User', backref='user_ratings')
    movie = db.relationship('Movie', backref='ratings_entries')  # 改为 backref='ratings_entries'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# 检查文件类型
def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


# 路由定义（与之前相同，无修改）
@app.route('/')
def home():
    movies = Movie.query.order_by(Movie.upload_date.desc()).all()
    return render_template('index.html', movies=movies)


@app.route('/movies/<int:movie_id>')
def movie_detail(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    ratings = movie.ratings
    avg_rating = sum(r.rating for r in ratings) / len(ratings) if ratings else 0
    return render_template('movie_detail.html', movie=movie, avg_rating=avg_rating)


@app.route('/movies/genre/<genre>')
def movies_by_genre(genre):
    movies = Movie.query.filter_by(genre=genre).all()
    return render_template('index.html', movies=movies, genre=genre)


@app.route('/search')
def search_movies():
    query = request.args.get('query', '')
    movies = Movie.query.filter(
        (Movie.title.contains(query)) |
        (Movie.description.contains(query)) |
        (Movie.director.contains(query))
    ).order_by(Movie.upload_date.desc()).all()
    return render_template('index.html', movies=movies, query=query)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('两次输入的密码不一致')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('邮箱已被注册')
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('注册成功，请登录')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash('用户名或密码不正确')
            return redirect(url_for('login'))

        login_user(user)
        flash('登录成功')
        return redirect(url_for('home'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录')
    return redirect(url_for('home'))


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_movie():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        director = request.form['director']
        genre = request.form['genre']

        # 处理封面图片
        cover_image = None
        if 'cover_image' in request.files:
            file = request.files['cover_image']
            if file.filename:
                filename = secure_filename(file.filename)
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                cover_image = filename

        # 处理电影文件
        file_path = None
        if 'movie_file' in request.files:
            file = request.files['movie_file']
            if file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = filename  # 只存储文件名
                full_file_path = os.path.join(upload_folder, filename)
                file.save(full_file_path)

        movie = Movie(
            title=title,
            description=description,
            director=director,
            genre=genre,
            cover_image=cover_image,
            file_path=file_path,
            user_id=current_user.id
        )

        db.session.add(movie)
        db.session.commit()

        flash('电影上传成功')
        return redirect(url_for('home'))

    current_year = datetime.now().year
    return render_template('upload_movie.html', current_year=current_year)


@app.route('/movies/<int:movie_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)

    # 权限检查：仅上传者或管理员可编辑
    if current_user.id != movie.user.id and not current_user.is_admin:
        flash('没有权限编辑此电影')
        return redirect(url_for('movie_detail', movie_id=movie_id))

    if request.method == 'POST':
        # 更新基本信息
        movie.title = request.form.get('title', movie.title)
        movie.description = request.form.get('description', movie.description)
        movie.director = request.form.get('director', movie.director)
        movie.genre = request.form.get('genre', movie.genre)

        # 处理封面图片更新
        if 'cover_image' in request.files:
            file = request.files['cover_image']
            if file.filename:
                # 删除旧封面
                if movie.cover_image:
                    old_cover_path = os.path.join(upload_folder, movie.cover_image)
                    if os.path.exists(old_cover_path):
                        os.remove(old_cover_path)

                filename = secure_filename(file.filename)
                new_cover_path = os.path.join(upload_folder, filename)
                file.save(new_cover_path)
                movie.cover_image = filename

        # 处理电影文件更新
        if 'movie_file' in request.files:
            file = request.files['movie_file']
            if file.filename and allowed_file(file.filename):
                # 删除旧文件
                if movie.file_path:
                    old_file_path = os.path.join(upload_folder, movie.file_path)
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)

                filename = secure_filename(file.filename)
                new_file_path = os.path.join(upload_folder, filename)
                file.save(new_file_path)
                movie.file_path = filename

        db.session.commit()
        flash('电影信息已更新')
        return redirect(url_for('movie_detail', movie_id=movie_id))

    return render_template('edit_movie.html', movie=movie)


@app.route('/movies/<int:movie_id>/download')
@login_required
def download_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)

    if not movie.file_path:
        flash('该电影暂无可下载的文件')
        return redirect(url_for('movie_detail', movie_id=movie_id))

    # 清理路径前缀
    filename = movie.file_path
    for prefix in ['static/uploads/', 'uploads/']:
        if filename.startswith(prefix):
            filename = filename[len(prefix):]
            break

    # 构建完整路径
    file_path = os.path.join(upload_folder, filename)

    if not os.path.exists(file_path):
        flash(f'文件不存在: {movie.file_path}')
        return redirect(url_for('movie_detail', movie_id=movie_id))

    # 更新数据库路径（如有必要）
    if movie.file_path != filename:
        movie.file_path = filename
        db.session.commit()

    return send_file(file_path, as_attachment=True, download_name=filename)


@app.route('/movies/<int:movie_id>/comment', methods=['POST'])
@login_required
def add_comment(movie_id):
    content = request.form['content']
    comment = Comment(content=content, user_id=current_user.id, movie_id=movie_id)
    db.session.add(comment)
    db.session.commit()
    flash('评论已添加')
    return redirect(url_for('movie_detail', movie_id=movie_id))


@app.route('/movies/<int:movie_id>/rate', methods=['POST'])
@login_required
def rate_movie(movie_id):
    rating_value = int(request.form['rating'])

    # 检查用户是否已经评过分
    existing_rating = Rating.query.filter_by(
        user_id=current_user.id,
        movie_id=movie_id
    ).first()

    if existing_rating:
        existing_rating.rating = rating_value
        flash('您已更新评分')
    else:
        # 创建新评分
        rating = Rating(
            rating=rating_value,
            user_id=current_user.id,
            movie_id=movie_id
        )
        db.session.add(rating)
        flash('评分已提交')

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash('评分提交失败，您可能已经评分过了')

    return redirect(url_for('movie_detail', movie_id=movie_id))


if __name__ == '__main__':
    # with app.app_context():
    #     db.drop_all()  # 删除所有表
    #     db.create_all()  # 重新创建所有表
    app.run(debug=True)