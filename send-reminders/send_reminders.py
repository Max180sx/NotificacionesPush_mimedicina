import firebase_admin
from firebase_admin import credentials, firestore, messaging
from datetime import datetime
import json
import os

def initialize_firebase():
    service_account_json = os.environ.get("SERVICE_ACCOUNT_KEY")
    if not service_account_json:
        raise ValueError("Falta la variable SERVICE_ACCOUNT_KEY")
    cred = credentials.Certificate(json.loads(service_account_json))
    firebase_admin.initialize_app(cred)

def reset_taken_flags(db):
    today_str = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()

    users_ref = db.collection('users')
    users = users_ref.stream()

    for user in users:
        user_id = user.id
        meds_ref = users_ref.document(user_id).collection('medications')
        meds = meds_ref.stream()

        for med in meds:
            med_data = med.to_dict()
            med_id = med.id
            last_taken = med_data.get("lastTakenDate")
            hour = med_data.get("hourToTake")
            minute = med_data.get("minuteToTake")

            # Si ya se tomó hoy, no hacer nada
            if last_taken == today_str:
                continue

            # Si la hora programada ya pasó hoy, se reinicia `taken`
            med_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now >= med_time:
                try:
                    meds_ref.document(med_id).update({"taken": False})
                    print(f"Reiniciado 'taken' de '{med_data.get('name')}' para usuario {user_id}")
                except Exception as e:
                    print(f"Error reiniciando medicamento {med_id}: {e}")

def send_reminders():
    db = firestore.client()
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute
    today_str = now.strftime("%Y-%m-%d")

    users_ref = db.collection('users')
    users = users_ref.stream()

    for user in users:
        user_data = user.to_dict()
        user_id = user.id
        fcm_token = user_data.get('fcmToken')
        name = user_data.get('name', 'Usuario')

        if not fcm_token:
            continue

        meds_ref = users_ref.document(user_id).collection('medications')
        meds = meds_ref.stream()

        for med in meds:
            med_data = med.to_dict()
            hour = med_data.get("hourToTake")
            minute = med_data.get("minuteToTake")
            taken = med_data.get("taken", False)
            enabled = med_data.get("enabled", False)

            if not enabled or taken:
                continue

            if hour == current_hour and minute == current_minute:
                try:
                    # Enviar notificación push
                    message = messaging.Message(
                        token=fcm_token,
                        notification=messaging.Notification(
                            title="Hora de tu medicina 💊",
                            body=f"Toma: {med_data.get('name')} - {med_data.get('dosage')}",
                        ),
                        data={"route": "notifications"},
                    )
                    response = messaging.send(message)
                    print(f"✅ Notificación enviada a {name} ({user_id}): {response}")
                except Exception as e:
                    print(f"❌ Error enviando notificación a {name}: {e}")

if __name__ == "__main__":
    initialize_firebase()
    db = firestore.client()
    reset_taken_flags(db)
    send_reminders()
