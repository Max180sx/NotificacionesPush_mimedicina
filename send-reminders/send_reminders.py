import firebase_admin
from firebase_admin import credentials, firestore, messaging
from datetime import datetime
import json
import os

def initialize_firebase():
    # Cargar credencial desde variable de entorno
    service_account_json = os.environ.get("SERVICE_ACCOUNT_KEY")
    if not service_account_json:
        raise ValueError("Falta la variable SERVICE_ACCOUNT_KEY")
    cred = credentials.Certificate(json.loads(service_account_json))
    firebase_admin.initialize_app(cred)

def send_reminders():
    db = firestore.client()
    now = datetime.now()
    current_hour = now.strftime("%H:%M")  # ejemplo: '14:30'

    users_ref = db.collection('users')
    users = users_ref.stream()

    for user in users:
        data = user.to_dict()
        reminder_time = data.get('reminderTime')  # asegúrate de que esta clave exista
        fcm_token = data.get('fcmToken')

        if reminder_time == current_hour and fcm_token:
            # Enviar notificación
            message = messaging.Message(
                token=fcm_token,
                notification=messaging.Notification(
                    title="Hora de tu medicina 💊",
                    body="Es hora de tomar tu medicamento.",
                ),
                data={"route": "notifications"},
            )
            try:
                response = messaging.send(message)
                print(f"Notificación enviada a {data.get('name')}, response: {response}")
            except Exception as e:
                print(f"Error al enviar notificación a {data.get('name')}: {e}")

if __name__ == "__main__":
    initialize_firebase()
    send_reminders()
