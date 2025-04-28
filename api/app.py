from flask import Flask, render_template, request, redirect, url_for, flash
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, FloatField, SubmitField
from wtforms.validators import DataRequired, Email
from pymongo import MongoClient
from setting import Config
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
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

# Khởi tạo Brevo
configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = app.config["BREVO_API_KEY"]
api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

# Form tạo đơn hàng
class OrderForm(FlaskForm):
    customer_name = StringField("Tên khách hàng", validators=[DataRequired()])
    customer_email = StringField("Email", validators=[DataRequired(), Email()])
    product_name = StringField("Tên sản phẩm", validators=[DataRequired()])
    product_price = FloatField("Giá sản phẩm", validators=[DataRequired()])
    product_image = FileField("Ảnh sản phẩm", validators=[FileAllowed(['jpg', 'png', 'jpeg'], 'Chỉ cho phép ảnh JPG, PNG!')])
    submit = SubmitField("Tạo đơn hàng")

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
            "email_opened": False
        }
        orders_collection.insert_one(order_data)

        # Gửi email thông báo
        send_order_email(order_data)

        flash("Đơn hàng đã được tạo và email đã được gửi!", "success")
        return redirect(url_for("create_order"))
    return render_template("order_form.html", form=form)

def send_order_email(order):
    sender = {"name": "Đội ngũ bán hàng", "email": app.config["MAIL_USERNAME"]}
    to = [{"email": order["customer_email"], "name": order["customer_name"]}]
    html_content = render_template(
        "email_template.html",
        order=order,
        tracking_pixel=url_for("view_order", order_id=order["order_id"], _external=True)
    )
    # Gắn order_id vào tags để nhận diện trong webhook
    tags = [order["order_id"]]
    try:
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            sender=sender,
            to=to,
            subject="Xác nhận đơn hàng",
            html_content=html_content,
            tags=tags
        )
        api_instance.send_transac_email(send_smtp_email)
        print(f"Email sent to {order['customer_email']}")
    except ApiException as e:
        print(f"Error sending email: {e}")

@app.route("/order/<order_id>")
def view_order(order_id):
    order = orders_collection.find_one({"order_id": order_id})
    if not order:
        return "Đơn hàng không tồn tại", 404
    # Cập nhật trạng thái email_opened (khi người dùng nhấp vào liên kết)
    orders_collection.update_one(
        {"order_id": order_id},
        {"$set": {"email_opened": True}}
    )
    return render_template("order_detail.html", order=order)

@app.route("/orders")
def view_orders():
    orders = list(orders_collection.find())
    return render_template("orders.html", orders=orders)

# Webhook để nhận sự kiện từ Brevo
@app.route("/webhook", methods=["POST"])
def brevo_webhook():
    events = request.get_json()
    for event in events:
        if event.get("event") == "opened":
            order_id = event.get("tags", [None])[0]  # Lấy order_id từ tags
            if order_id:
                orders_collection.update_one(
                    {"order_id": order_id},
                    {"$set": {"email_opened": True}}
                )
                print(f"Email opened for order {order_id}")
    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)