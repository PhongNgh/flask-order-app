from flask import Flask, render_template, request, redirect, url_for, flash
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, FloatField, SubmitField
from wtforms.validators import DataRequired, Email
from pymongo import MongoClient
from setting import Config
from flask_mail import Mail, Message
import uuid
import cloudinary
import cloudinary.uploader
from io import BytesIO

app = Flask(__name__, template_folder="templates")
app.config.from_object(Config)

# Kết nối MongoDB
client = MongoClient(app.config["MONGO_URI"])
db = client.get_database()
orders_collection = db.orders

# Cấu hình Flask-Mail
mail = Mail(app)

# Form tạo đơn hàng
class OrderForm(FlaskForm):
    customer_name = StringField("Tên khách hàng", validators=[DataRequired()])
    customer_email = StringField("Email", validators=[DataRequired(), Email()])
    product_name = StringField("Tên sản phẩm", validators=[DataRequired()])
    product_price = FloatField("Giá sản phẩm", validators=[DataRequired()])
    product_image = FileField("Ảnh sản phẩm", validators=[FileAllowed(['jpg', 'png', 'jpeg'], 'Chỉ cho phép ảnh JPG, PNG!')])
    submit = SubmitField("Tạo đơn hàng")

# Tạo tracking pixel và tải lên Cloudinary (chỉ tạo một lần)
def create_and_upload_tracking_pixel():
    from PIL import Image
    img = Image.new("RGB", (1, 1), color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    # Tải lên Cloudinary
    response = cloudinary.uploader.upload(
        buffer,
        folder="tracking_pixels",
        public_id="tracking_pixel",
        overwrite=True
    )
    return response["secure_url"]

# Lấy URL tracking pixel từ Cloudinary
tracking_pixel_base_url = create_and_upload_tracking_pixel()

@app.route("/", methods=["GET", "POST"])
def create_order():
    form = OrderForm()
    if form.validate_on_submit():
        order_id = str(uuid.uuid4())
        
        # Xử lý ảnh sản phẩm
        product_image_url = None
        if form.product_image.data:
            image_file = form.product_image.data
            response = cloudinary.uploader.upload(
                image_file,
                folder="product_images",
                public_id=f"product_{order_id}"
            )
            product_image_url = response["secure_url"]
        
        # Lưu đơn hàng vào MongoDB
        order_data = {
            "order_id": order_id,
            "customer_name": form.customer_name.data,
            "customer_email": form.customer_email.data,
            "product_name": form.product_name.data,
            "product_price": form.product_price.data,
            "product_image_url": product_image_url,
            "email_opened": False,
            "tracking_pixel_url": f"{url_for('track_email', order_id=order_id, _external=True)}"
        }
        orders_collection.insert_one(order_data)

        # Gửi email thông báo
        send_order_email(order_data)

        flash("Đơn hàng đã được tạo và email đã được gửi!", "success")
        return redirect(url_for("create_order"))
    return render_template("order_form.html", form=form)

def send_order_email(order):
    msg = Message(
        subject="Xác nhận đơn hàng",
        sender=app.config["MAIL_USERNAME"],
        recipients=[order["customer_email"]]
    )
    # Nội dung email với tracking pixel từ Cloudinary
    msg.html = render_template(
        "email_template.html",
        order=order,
        tracking_pixel=order["tracking_pixel_url"]
    )
    mail.send(msg)

@app.route("/track/<order_id>")
def track_email(order_id):
    # Cập nhật trạng thái email_opened
    orders_collection.update_one(
        {"order_id": order_id},
        {"$set": {"email_opened": True}}
    )
    # Trả về URL của tracking pixel từ Cloudinary
    return redirect(tracking_pixel_base_url)

@app.route("/orders")
def view_orders():
    orders = list(orders_collection.find())
    return render_template("orders.html", orders=orders)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)