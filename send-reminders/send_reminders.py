import firebase_admin
from firebase_admin import credentials, firestore, messaging
from datetime import datetime
from pytz import timezone
import json
import os
from google.cloud.firestore_v1 import FieldFilter

# 🔐 Inicializa Firebase con clave de servicio desde variable de entorno
def initialize_firebase():
    service_account_json = os.environ.get("SERVICE_ACCOUNT_KEY")
    if not service_account_json:
        raise ValueError("Falta la variable SERVICE_ACCOUNT_KEY")
    cred = credentials.Certificate(json.loads(service_account_json))
    firebase_admin.initialize_app(cred)

# ⏰ Devuelve la hora actual en zona horaria de Chile
def get_local_time():
    chile_tz = timezone("America/Santiago")
    return datetime.now(chile_tz)

# ♻️ Reinicia "taken=False" si corresponde
def reset_taken_flags(db):
    now = get_local_time()
    today_str = now.strftime("%Y-%m-%d")

    users = db.collection('users').stream()
    for user in users:
        user_id = user.id
        meds = db.collection('users').document(user_id).collection('medications').stream()

        for med in meds:
            data = med.to_dict()
            last_taken = data.get("lastTakenDate")
            hour = data.get("hourToTake")
            minute = data.get("minuteToTake")

            if last_taken == today_str:
                continue

            med_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now >= med_time:
                try:
                    db.collection('users').document(user_id).collection('medications').document(med.id).update({"taken": False})
                    print(f"♻️ Reiniciado 'taken' de '{data.get('name')}' para {user_id}")
                except Exception as e:
                    print(f"❌ Error reiniciando '{data.get('name')}': {e}")

# 📏 Determina si estamos dentro del rango de minutos alrededor de la hora programada
def is_within_minutes(target_hour, target_minute, window=2):
    now = get_local_time()
    target_time = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    delta = abs((now - target_time).total_seconds()) / 60
    return delta <= window

# 📲 Notifica al paciente vía FCM
def notify_user(user_id, fcm_token, med_name, dosage):
    try:
        message = messaging.Message(
            token=fcm_token,
            notification=messaging.Notification(
                title="Hora de tu medicina 💊",
                body=f"Toma: {med_name} - {dosage}",
            ),
            data={"route": "notifications"},
        )
        response = messaging.send(message)
        print(f"✅ Notificación enviada al usuario {user_id}: {response}")
    except Exception as e:
        print(f"❌ Error notificando a {user_id}: {e}")

# 📡 Notifica al cuidador por FCM y registra en Firestore
def notify_caregiver(db, caregiver_id, title, body):
    doc_ref = db.collection("users").document(caregiver_id)
    caregiver_doc = doc_ref.get()
    caregiver_data = caregiver_doc.to_dict()
    fcm_token = caregiver_data.get("fcmToken")

    if fcm_token:
        try:
            message = messaging.Message(
                token=fcm_token,
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data={"type": "medication", "route": "notifications"},
            )
            messaging.send(message)
            print(f"📲 Notificado cuidador {caregiver_id}")
        except Exception as e:
            print(f"❌ FCM error cuidador {caregiver_id}: {e}")

    # Registro en Firestore
    doc_ref.collection("notifications").add({
        "title": title,
        "body": body,
        "type": "medication",
        "read": False,
        "timestamp": firestore.SERVER_TIMESTAMP,
    })

    # Contador de notificaciones no leídas
    doc_ref.update({
        "unreadNotifications": firestore.Increment(1)
    })

# 🚀 Procesa notificaciones y alertas
def send_all_notifications(db):
    now = get_local_time()
    today_str = now.strftime("%Y-%m-%d")
    current_hour, current_minute = now.hour, now.minute

    users = db.collection('users').stream()
    for user in users:
        user_id = user.id
        user_data = user.to_dict()
        user_name = user_data.get('name', 'Usuario')
        fcm_token = user_data.get('fcmToken')

        meds = db.collection('users').document(user_id).collection('medications').stream()
        for med in meds:
            data = med.to_dict()
            name = data.get("name", "medicina")
            dosage = data.get("dosage", "")
            hour = data.get("hourToTake")
            minute = data.get("minuteToTake")
            taken = data.get("taken", False)
            enabled = data.get("enabled", False)
            last_taken = data.get("lastTakenDate")

            if not enabled:
                continue

            print(f"⏰ {user_name} - {name} ({hour}:{minute}) - actual: {current_hour}:{current_minute}, taken={taken}")
            scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # 🔔 Recordatorio
            if is_within_minutes(hour, minute) and not taken:
                if fcm_token:
                    notify_user(user_id, fcm_token, name, dosage)

            # 🟢 Confirmación al cuidador
            elif last_taken == today_str and taken:
                links = db.collection("caregiver_links") \
                    .where(filter=FieldFilter("patientId", "==", user_id)).stream()

                for link in links:
                    caregiver_id = link.to_dict().get("caregiverId")
                    if caregiver_id:
                        title = f"{user_name} tomó su medicina ✅"
                        body = f"{name} fue tomado hoy ({today_str})"
                        notify_caregiver(db, caregiver_id, title, body)

            # 🔴 Atraso
            elif not taken and now > scheduled_time and last_taken != today_str:
                links = db.collection("caregiver_links") \
                    .where(filter=FieldFilter("patientId", "==", user_id)).stream()

                for link in links:
                    caregiver_id = link.to_dict().get("caregiverId")
                    if caregiver_id:
                        title = f"{user_name} NO tomó su medicina ❗"
                        body = f"{name} debió tomarse a las {hour:02}:{minute:02}"
                        notify_caregiver(db, caregiver_id, title, body)

# 🔁 Ejecuta todo
def main():
    try:
        print("🔵 Ejecutando script de recordatorios...")
        initialize_firebase()
        db = firestore.client()
        reset_taken_flags(db)
        send_all_notifications(db)
        print("✅ Script completado")
    except Exception as e:
        print(f"❌ Excepción atrapada: {e}")

if __name__ == "__main__":
    main()
