import os
from werkzeug.utils import secure_filename
from datetime import datetime
from google.cloud import firestore

from flask import Flask, render_template, request, redirect, session
import pyrebase
import json

app = Flask(__name__)
app.secret_key = "super-secret-key"  # 可以隨便寫一個字串

# 加在 app 最上方（若還沒加）
ICON_FOLDER = os.path.join("static", "icons")
os.makedirs(ICON_FOLDER, exist_ok=True)

FIXED_STEPS = [
    {"step_number": 1, "name": "線上諮詢時間"},
    {"step_number": 2, "name": "顧客建檔"},
    {"step_number": 3, "name": "確認場勘時間"},
    {"step_number": 4, "name": "場勘"},
    {"step_number": 5, "name": "報價與規劃"},
    {"step_number": 6, "name": "訂單取得與確認施工日期"},
    {"step_number": 7, "name": "竣工"},
    {"step_number": 8, "name": "付款及發票"},
    {"step_number": 9, "name": "結案及保固起算"}
]



from datetime import datetime, timedelta

def calculate_working_days(start_date, end_date):
    """計算兩日期之間的工作天（排除六日）"""
    if not start_date or not end_date:
        return None
    days = 0
    current = start_date
    while current < end_date:
        if current.weekday() < 5:  # 週一～週五
            days += 1
        current += timedelta(days=1)
    return days



@app.route("/admin/project/<project_id>/steps", methods=["GET", "POST"])
def manage_fixed_steps(project_id):
    if "user" not in session or session.get("role") != "staff":
        return redirect("/")

    FIXED_STEPS = [
        {"step_number": 1, "name": "線上諮詢時間"},
        {"step_number": 2, "name": "顧客建檔"},
        {"step_number": 3, "name": "確認場勘時間"},
        {"step_number": 4, "name": "場勘"},
        {"step_number": 5, "name": "報價與規劃"},
        {"step_number": 6, "name": "訂單取得與確認施工日期"},
        {"step_number": 7, "name": "竣工"},
        {"step_number": 8, "name": "付款及發票"},
        {"step_number": 9, "name": "結案及保固起算"}
    ]

    project_ref = db.collection("projects").document(project_id)
    project_data = project_ref.get().to_dict()
    

    step_docs = list(project_ref.collection("steps").order_by("step_number").stream())

    # 🔧 若步驟資料不存在，則補上所有固定步驟
    if not step_docs:
        for step in FIXED_STEPS:
            project_ref.collection("steps").add({
                "step_number": step["step_number"],
                "name": step["name"],
                "enabled": True,
                "completed_at": None
            })
        # 重新讀取一次補齊後的資料
        step_docs = list(project_ref.collection("steps").order_by("step_number").stream())





    if request.method == "POST":
        for doc in step_docs:
            data = doc.to_dict()
            step_number = data.get("step_number")
            enabled_field = f"enabled_{step_number}"
            completed_field = f"completed_at_{step_number}"

            completed_at_raw = request.form.get(completed_field)
            completed_at = datetime.strptime(completed_at_raw, "%Y-%m-%dT%H:%M") if completed_at_raw else None

            is_enabled = request.form.get(enabled_field) == "on"
            if completed_at:
                is_enabled = True

            updates = {
                "enabled": is_enabled,
                "completed_at": completed_at
            }

            if step_number == 6:
                order_received_raw = request.form.get("order_received_at_6")
                construction_date_raw = request.form.get("construction_date_6")
                order_received_at = datetime.strptime(order_received_raw, "%Y-%m-%dT%H:%M") if order_received_raw else None
                construction_date = datetime.strptime(construction_date_raw, "%Y-%m-%dT%H:%M") if construction_date_raw else None
                updates["order_received_at"] = order_received_at
                updates["construction_date"] = construction_date

            doc.reference.update(updates)

        # 自動填入第9步（保固起算）
        step7_doc = next((d for d in step_docs if d.to_dict().get("step_number") == 7), None)
        step8_doc = next((d for d in step_docs if d.to_dict().get("step_number") == 8), None)
        step9_doc = next((d for d in step_docs if d.to_dict().get("step_number") == 9), None)

        if step7_doc and step8_doc and step9_doc:
            step7_data = step7_doc.to_dict()
            step8_data = step8_doc.to_dict()

            if step7_data.get("completed_at") and step8_data.get("completed_at"):
                warranty_start_at = step7_data.get("completed_at")
                completed_at_9 = warranty_start_at

                step9_doc.reference.set({
                    "step_number": 9,
                    "name": "結案及保固起算",
                    "enabled": True,
                    "completed_at": completed_at_9,
                    "warranty_start_at": warranty_start_at
                }, merge=True)

        return redirect(f"/admin/project/{project_id}/steps")

    # GET 模式
    steps = []
    cumulative_days = 0
    prev_completed = None

    for doc in step_docs:
        data = doc.to_dict()
        step_number = data["step_number"]

        if step_number == 6:
            completed_at = data.get("construction_date")
        elif step_number == 9:
            completed_at = data.get("warranty_start_at") or data.get("completed_at")
        else:
            completed_at = data.get("completed_at")

        enabled = data.get("enabled", False) or completed_at is not None
        duration = None

        if enabled and completed_at:
            if prev_completed:
                duration = calculate_working_days(prev_completed, completed_at)
                cumulative_days += duration
            else:
                duration = 0
                cumulative_days = 0
            prev_completed = completed_at

        warranty_start = data.get("warranty_start_at")
        warranty_expire = None
        if step_number == 9 and warranty_start:
            warranty_expire = (warranty_start + timedelta(days=365)).strftime("%Y-%m-%d")

        steps.append({
            "step_number": step_number,
            "name": data["name"],
            "enabled": enabled,
            "completed_at": completed_at.strftime("%Y-%m-%dT%H:%M") if completed_at else None,
            "duration": duration,
            "cumulative": cumulative_days if enabled and completed_at else None,
            "order_received_at": data.get("order_received_at").strftime("%Y-%m-%dT%H:%M") if data.get("order_received_at") else None,
            "construction_date": data.get("construction_date").strftime("%Y-%m-%dT%H:%M") if data.get("construction_date") else None,
            "warranty_expire_at": warranty_expire,
            "warranty_start_at": warranty_start.strftime("%Y-%m-%dT%H:%M") if warranty_start else None
        })

    return render_template("edit_steps.html", steps=steps, project_title=project_data["title"])





@app.route("/admin/assign_projects_to_user", methods=["GET", "POST"])
def assign_projects_to_user():
    if "user" not in session or session.get("role") != "staff":
        return redirect("/")

    if request.method == "POST":
        phone = request.form["phone"]
        selected_project_ids = request.form.getlist("projects")

        # 刪除所有現有授權
        perms = db.collection("project_permissions").where("phone", "==", phone).stream()
        for perm in perms:
            db.collection("project_permissions").document(perm.id).delete()

        # 加入新授權
        for pid in selected_project_ids:
            db.collection("project_permissions").add({
                "phone": phone,
                "project_id": pid
            })

        return redirect("/admin/assign_projects_to_user?phone=" + phone)

    # GET 模式
    selected_phone = request.args.get("phone")

    # 撈出所有顧客與業務帳號
    users = db.collection("users").where("role", "in", ["customer", "sales"]).stream()
    user_list = [doc.to_dict() for doc in users]

    # 撈出所有專案
    projects = db.collection("projects").stream()
    project_list = [{"id": doc.id, "title": doc.to_dict().get("title", "")} for doc in projects]

    # 該使用者已授權專案
    current_project_ids = []
    if selected_phone:
        perms = db.collection("project_permissions").where("phone", "==", selected_phone).stream()
        current_project_ids = [p.to_dict()["project_id"] for p in perms]

    return render_template("assign_projects_to_user.html",
                           user_list=user_list,
                           selected_phone=selected_phone,
                           project_list=project_list,
                           current_project_ids=current_project_ids)


@app.route("/admin/delete_user/<id>", methods=["POST"])
def delete_user(id):
    if "user" not in session or session.get("role") != "staff":
        return redirect("/")

    doc_ref = db.collection("users").document(id)
    doc = doc_ref.get()
    if not doc.exists:
        return redirect("/admin/manage_users?message=找不到該帳號")

    phone = doc.to_dict().get("phone")

    # 檢查是否仍有專案授權
    perms = db.collection("project_permissions").where("phone", "==", phone).stream()
    if any(True for _ in perms):
        return redirect(f"/admin/manage_users?message=帳號 {phone} 仍有授權，無法刪除")

    doc_ref.delete()
    return redirect(f"/admin/manage_users?message=帳號 {phone} 已刪除")




@app.route("/admin/upload_step_icons", methods=["GET", "POST"])
def upload_step_icons():
    if "user" not in session or session.get("role") != "staff":
        return redirect("/")

    if request.method == "POST":
        for i in range(1, 10):
            file = request.files.get(f"step{i}")
            if file and file.filename != "":
                filename = secure_filename(f"step{i}.png")
                file.save(os.path.join(ICON_FOLDER, filename))

        return redirect("/admin/upload_step_icons")

    return render_template("upload_step_icons.html")


# 載入 Firebase 設定
with open("firebase_config.json") as f:
    config = json.load(f)

firebase = pyrebase.initialize_app(config)

# Firestore 初始化
import google.auth
from google.oauth2 import service_account

firebase_cred_json = os.environ.get("FIREBASE_CREDENTIAL_JSON")
if not firebase_cred_json:
    raise ValueError("FIREBASE_CREDENTIAL_JSON 環境變數未設定")

cred = service_account.Credentials.from_service_account_info(json.loads(firebase_cred_json))
db = firestore.Client(credentials=cred, project=cred.project_id)


auth = firebase.auth()

@app.route("/")
def index():
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    phone = request.form["phone"]
    password = request.form["password"]

    user_docs = db.collection("users").where("phone", "==", phone).stream()
    user_data = None
    for doc in user_docs:
        user_data = doc.to_dict()
        break

    if not user_data or user_data.get("password") != password:
        return render_template("login.html", error="登入失敗，請確認手機號碼與密碼")


    session["user"] = phone
    session["role"] = user_data.get("role", "customer")

    if session["role"] == "customer":
        return redirect("/dashboard")
    elif session["role"] == "staff":
        return redirect("/admin")
    elif session["role"] == "sales":
        return redirect("/sales_dashboard")
    else:
        return render_template("login.html", error="未知身份，無法登入")

@app.route("/sales_dashboard")
def sales_dashboard():
    if "user" not in session or session.get("role") != "sales":
        return redirect("/")

    phone = session["user"]

    # 查詢該業務能查看的專案（透過授權資料）
    perms = db.collection("project_permissions").where("phone", "==", phone).stream()
    project_ids = [perm.to_dict()["project_id"] for perm in perms]

    project_list = []
    for pid in project_ids:
        doc = db.collection("projects").document(pid).get()
        if doc.exists:
            data = doc.to_dict()
            project_list.append({
                "id": pid,
                "title": data.get("title", "（未命名）"),
                "client_phone": data.get("client_phone", "（未指定）"),
                "client_name": data.get("client_name", "（未填）"),
                "install_address": data.get("install_address", "（未填）"),
                "status": data.get("status", "未知")
            })

    return render_template("sales_dashboard.html", projects=project_list, user=phone)


@app.route("/admin/remove_permission", methods=["POST"])
def remove_permission():
    if "user" not in session or session.get("role") != "staff":
        return redirect("/")

    phone = request.form["phone"]
    project_id = request.form["project_id"]

    # 找出符合條件的權限紀錄並刪除
    perms = db.collection("project_permissions")\
              .where("phone", "==", phone)\
              .where("project_id", "==", project_id).stream()

    for perm in perms:
        db.collection("project_permissions").document(perm.id).delete()

    return redirect("/admin")


@app.route("/admin/delete_project", methods=["POST"])
def delete_project():
    if "user" not in session or session.get("role") != "staff":
        return redirect("/")

    project_id = request.form["project_id"]

    # 1. 刪除 projects 中的該專案
    db.collection("projects").document(project_id).delete()

    # 2. 刪除 project_permissions 中的所有相關授權
    perms = db.collection("project_permissions").where("project_id", "==", project_id).stream()
    for perm in perms:
        db.collection("project_permissions").document(perm.id).delete()

    # 3. 刪除 steps 中該專案的所有進度紀錄
    steps = db.collection("steps").where("project_id", "==", project_id).stream()
    for step in steps:
        db.collection("steps").document(step.id).delete()

    return redirect("/admin")



@app.route("/admin/new_project", methods=["GET", "POST"])
def new_project():
    if "user" not in session or session.get("role") != "staff":
        return redirect("/")

    if request.method == "POST":
        title = request.form["title"]
        client_phone = request.form["client_phone"]
        client_name = request.form.get("client_name", "")
        install_address = request.form.get("install_address", "")
        viewers = request.form.getlist("viewers")
        sales_viewers = request.form.getlist("sales_viewers")
        created_at = datetime.now()

        # 建立專案資料
        project_ref = db.collection("projects").document()
        project_ref.set({
            "title": title,
            "client_phone": client_phone,
            "client_name": client_name,
            "install_address": install_address,
            "status": "尚未開始",  # ✅ 自動加上預設狀態
            "created_at": created_at
        })

        # 建立授權資料
        for phone in viewers + sales_viewers:
            db.collection("project_permissions").add({
                "phone": phone,
                "project_id": project_ref.id
            })

        # 建立固定進度步驟（全部預設啟用）
        for step in FIXED_STEPS:
            project_ref.collection("steps").add({
                "step_number": step["step_number"],
                "name": step["name"],
                "enabled": True,
                "completed_at": None
            })

        return redirect("/admin")

    # GET：撈出顧客與業務清單
    customer_docs = db.collection("users").where("role", "==", "customer").stream()
    customer_list = [doc.to_dict() for doc in customer_docs]

    sales_docs = db.collection("users").where("role", "==", "sales").stream()
    sales_list = [doc.to_dict() for doc in sales_docs]

    return render_template("new_project.html", customer_list=customer_list, sales_list=sales_list)







@app.route("/admin")
def admin_dashboard():
    if "user" not in session or session.get("role") not in ["staff", "sales"]:
        return redirect("/")

    projects_ref = db.collection("projects").order_by("created_at", direction=firestore.Query.DESCENDING)
    projects = projects_ref.stream()

    project_list = []

    for project in projects:
        data = project.to_dict()
        project_id = project.id

        # 查詢授權帳號
        perms = db.collection("project_permissions").where("project_id", "==", project_id).stream()
        authorized_users = []
        for perm in perms:
            phone = perm.to_dict().get("phone")
            user_docs = db.collection("users").where("phone", "==", phone).get()
            role = user_docs[0].to_dict().get("role", "未知") if user_docs else "未知"
            authorized_users.append({
                "phone": phone,
                "role": role
            })

        # ✅ 補上 client_name 與 install_address
        project_list.append({
            "id": project_id,
            "title": data.get("title", "（未命名）"),
            "client_phone": data.get("client_phone", "（未指定）"),
            "client_name": data.get("client_name", "（未填）"),
            "install_address": data.get("install_address", "（未填）"),
            "status": data.get("status", "未知"),
            "authorized_users": authorized_users
        })

    return render_template("admin_dashboard.html", projects=project_list, user=session["user"])




@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    phone = session["user"]

    # 取得這個用戶授權的專案 IDs
    perms = db.collection("project_permissions").where("phone", "==", phone).stream()
    project_ids = [perm.to_dict()["project_id"] for perm in perms]

    # 逐一查詢專案（也可以改成批量查詢）
    project_list = []
    for pid in project_ids:
        project_doc = db.collection("projects").document(pid).get()
        if project_doc.exists:
            data = project_doc.to_dict()
            project_list.append({
                "id": pid,
                "title": data.get("title", "（未命名）"),
                "client_name": data.get("client_name", "（未填）"),
                "install_address": data.get("install_address", "（未填）"),
            })


    return render_template("dashboard.html", projects=project_list, user=phone)




@app.route("/project/<project_id>")
def project_detail(project_id):
    if "user" not in session or session.get("role") not in ["customer", "sales", "staff"]:
        return redirect("/")

    project_ref = db.collection("projects").document(project_id)
    project = project_ref.get().to_dict()

    # 取得固定步驟（只顯示已啟用的）
    step_docs = project_ref.collection("steps").order_by("step_number").stream()
    steps = []
    for doc in step_docs:
        data = doc.to_dict()
        if not data.get("completed_at"):  # 改成只忽略沒完成的
            continue
        steps.append({
            "step_number": data["step_number"],
            "name": data["name"],
            "completed_at": data.get("completed_at"),
            "order_received_at": data.get("order_received_at"),
            "construction_date": data.get("construction_date")
        })


    return render_template("project_detail.html", project_title=project.get("title"), steps=steps)

@app.route("/admin/manage_users", methods=["GET", "POST"])
def manage_users():
    if "user" not in session or session.get("role") != "staff":
        return redirect("/")

    message = ""
    if request.method == "POST":
        phone = request.form["phone"]
        password = request.form["password"]
        name = request.form.get("name", "")
        role = request.form.get("role", "")
        if role not in ["customer", "sales"]:
            message = "請選擇正確身份"
        else:
            exists = db.collection("users").where("phone", "==", phone).get()
            if len(exists) > 0:
                message = f"手機號碼 {phone} 已存在"
            else:
                db.collection("users").add({
                    "phone": phone,
                    "password": password,
                    "name": name,
                    "role": role
                })
                message = f"已成功新增帳號 {phone}"

    users = db.collection("users").where("role", "in", ["customer", "sales"]).stream()
    user_list = [dict(doc.to_dict(), id=doc.id) for doc in users]
    return render_template("manage_users.html", users=user_list, message=message)


@app.route("/admin/edit_user/<id>", methods=["GET", "POST"])
def edit_user(id):
    if "user" not in session or session.get("role") != "staff":
        return redirect("/")

    doc_ref = db.collection("users").document(id)
    doc = doc_ref.get()
    if not doc.exists:
        return "找不到該使用者"

    if request.method == "POST":
        phone = request.form["phone"]
        name = request.form.get("name", "")
        password = request.form.get("password", "")
        updates = {"phone": phone, "name": name}
        if password.strip():
            updates["password"] = password
        doc_ref.update(updates)
        return redirect("/admin/manage_users?message=帳號已更新")

    user = doc.to_dict()
    return render_template("edit_customer.html", user=user, id=id)  # 可重用舊畫面



@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
