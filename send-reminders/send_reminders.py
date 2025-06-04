import firebase_admin
from firebase_admin import credentials, firestore, messaging
from datetime import datetime, timedelta
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

# 📅 Calcula la próxima hora programada para notificar (hoy o mañana)
def calculate_next_notification_time(hour, minute):
    now = get_local_time()
    scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now > scheduled_time:
        scheduled_time += timedelta(days=1)
    return scheduled_time.isoformat()

# ♻️ Reinicia "taken=False" y programa la próxima notificación al cambiar de día
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

            if last_taken == today_str:
                continue

            hour = data.get("hourToTake")
            minute = data.get("minuteToTake")
            med_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            if now >= med_time:
                try:
                    db.collection('users').document(user_id).collection('medications').document(med.id).update({
                        "taken": False,
                        "nextNotificationTime": calculate_next_notification_time(hour, minute)
                    })
                    print(f"♻️ Reiniciado 'taken' y programado próxima notificación para '{data.get('name')}'")
                except Exception as e:
                    print(f"❌ Error reiniciando medicamento: {e}")

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
        print(f"✅ Notificación enviada a {user_id}: {med_name}")
    except Exception as e:
        print(f"❌ Error notificando a {user_id}: {e}")

# 📡 Notifica al cuidador y registra en Firestore
def notify_caregiver(db, caregiver_id, title, body):
    try:
        doc_ref = db.collection("users").document(caregiver_id)
        caregiver_data = doc_ref.get().to_dict()
        fcm_token = caregiver_data.get("fcmToken")

        if fcm_token:
            message = messaging.Message(
                token=fcm_token,
                notification=messaging.Notification(title=title, body=body),
                data={"type": "medication", "route": "notifications"},
            )
            messaging.send(message)
            print(f"📲 Notificado cuidador {caregiver_id}")

        doc_ref.collection("notifications").add({
            "title": title,
            "body": body,
            "type": "medication",
            "read": False,
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        doc_ref.update({"unreadNotifications": firestore.Increment(1)})
    except Exception as e:
        print(f"❌ Error notificando cuidador: {e}")

# 🚀 Procesa notificaciones solo cuando es el momento exacto
def send_all_notifications(db):
    now = get_local_time()
    today_str = now.strftime("%Y-%m-%d")

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
            next_notification = data.get("nextNotificationTime")

            if not enabled or not next_notification:
                continue

            scheduled_time = datetime.fromisoformat(next_notification)
            is_time_to_notify = now >= scheduled_time

            # 🔔 Notificación al paciente (solo si es la hora exacta y no se ha tomado)
            if is_time_to_notify and not taken and fcm_token:
                notify_user(user_id, fcm_token, name, dosage)
                new_next_time = calculate_next_notification_time(hour, minute)
                db.collection('users').document(user_id).collection('medications').document(med.id).update({
                    "nextNotificationTime": new_next_time
                })
                print(f"⏰ Recordatorio enviado a {user_name} para {name} a las {scheduled_time.strftime('%H:%M')}")

            # 🔴 Alerta de atraso al cuidador (si pasó la hora y no se ha tomado)
            if not taken and now > scheduled_time and data.get("lastTakenDate") != today_str:
                links = db.collection("caregiver_links").where(filter=FieldFilter("patientId", "==", user_id)).stream()
                for link in links:
                    caregiver_id = link.to_dict().get("caregiverId")
                    if caregiver_id:
                        title = f"{user_name} NO tomó su medicina ❗"
                        body = f"{name} debió tomarse a las {hour:02}:{minute:02}"
                        notify_caregiver(db, caregiver_id, title, body)
                        print(f"⚠️ Alerta de atraso enviada a cuidador de {user_name}")

# 🔁 Función principal
def main():
    try:
        print("\n🔵 Iniciando script de recordatorios...")
        initialize_firebase()
        db = firestore.client()
        reset_taken_flags(db)
        send_all_notifications(db)
        print("✅ Script completado a las:", get_local_time().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        print(f"❌ Error crítico: {e}")

if __name__ == "__main__":
    main()
