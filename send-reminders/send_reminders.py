import os
import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import requests

# Inicializar Firebase
cred = credentials.Certificate({
    "type": os.getenv("FIREBASE_TYPE"),
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL")
})

firebase_admin.initialize_app(cred)
db = firestore.client()

# Hora actual
now = datetime.datetime.now()
current_hour = now.strftime("%H:%M")

# Buscar usuarios que deban tomar medicina a esta hora
users_ref = db.collection("users")
users = users_ref.stream()

for user in users:
    data = user.to_dict()
    medication_times = data.get("medicationTimes", [])  # Ej: ["08:00", "14:00"]
    if current_hour in medication_times:
        token = data.get("fcmToken")
        if token:
            # Enviar notificación push
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"key={os.getenv('FCM_SERVER_KEY')}"
            }
            payload = {
                "to": token,
                "notification": {
                    "title": "Hora de tu medicina",
                    "body": "Es momento de tomar tu medicamento."
                },
                "data": {
                    "route": "notifications"
                }
            }
            response = requests.post("https://fcm.googleapis.com/fcm/send", json=payload, headers=headers)
            print(f"Notificación enviada a {data.get('name')}, respuesta: {response.status_code}")
