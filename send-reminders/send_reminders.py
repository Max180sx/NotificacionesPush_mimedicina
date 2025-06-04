import firebase_admin
from firebase_admin import credentials, firestore, messaging
from datetime import datetime, timedelta
from pytz import timezone
import json
import os
from google.cloud.firestore_v1 import FieldFilter

# 🔐 Inicializa Firebase
def initialize_firebase():
    service_account_json = os.environ.get("SERVICE_ACCOUNT_KEY")
    if not service_account_json:
        raise ValueError("Falta la variable SERVICE_ACCOUNT_KEY")
    cred = credentials.Certificate(json.loads(service_account_json))
    firebase_admin.initialize_app(cred)

# ⏰ Hora actual en Chile
def get_local_time():
    chile_tz = timezone("America/Santiago")
    return datetime.now(chile_tz)

# 📅 Calcula la próxima notificación para múltiples horarios
def calculate_next_notification(scheduled_times):
    now = get_local_time()
    
    for time in scheduled_times:
        scheduled_time = now.replace(
            hour=time["hour"],
            minute=time["minute"],
            second=0, microsecond=0
        )
        if scheduled_time > now:
            return scheduled_time.isoformat()
    
    # Si todos los horarios de hoy pasaron, programar para mañana
    first_time = scheduled_times[0]
    next_day = now + timedelta(days=1)
    return next_day.replace(
        hour=first_time["hour"],
        minute=first_time["minute"],
        second=0, microsecond=0
    ).isoformat()

# 🔄 Actualiza nextNotification para medicamentos existentes
def migrate_medication_data(db):
    users = db.collection('users').stream()
    for user in users:
        user_id = user.id
        meds = db.collection('users').document(user_id).collection('medications').stream()
        
        for med in meds:
            data = med.to_dict()
            if 'hourToTake' in data:  # Migrar estructura antigua
                new_data = {
                    "scheduledTimes": [{
                        "hour": data["hourToTake"],
                        "minute": data["minuteToTake"]
                    }],
                    "takenTimes": {},
                    "nextNotification": calculate_next_notification([{
                        "hour": data["hourToTake"],
                        "minute": data["minuteToTake"]
                    }])
                }
                med.reference.update(new_data)
                print(f"🔄 Migrado medicamento {med.id} para usuario {user_id}")

# 📲 Notificar al paciente
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
        messaging.send(message)
        print(f"✅ Notificación enviada a {user_id} para {med_name}")
    except Exception as e:
        print(f"❌ Error notificando a {user_id}: {e}")

# 📡 Notificar al cuidador
def notify_caregiver(db, caregiver_id, title, body):
    try:
        caregiver_ref = db.collection("users").document(caregiver_id)
        caregiver_data = caregiver_ref.get().to_dict()
        
        if caregiver_data.get("fcmToken"):
            message = messaging.Message(
                token=caregiver_data["fcmToken"],
                notification=messaging.Notification(title=title, body=body),
                data={"type": "medication", "route": "notifications"},
            )
            messaging.send(message)
        
        caregiver_ref.collection("notifications").add({
            "title": title,
            "body": body,
            "type": "medication",
            "read": False,
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        caregiver_ref.update({"unreadNotifications": firestore.Increment(1)})
    except Exception as e:
        print(f"❌ Error notificando cuidador: {e}")

# ♻️ Reiniciar estados diariamente
def reset_daily_states(db):
    today = get_local_time().strftime("%Y-%m-%d")
    
    users = db.collection('users').stream()
    for user in users:
        user_id = user.id
        meds = db.collection('users').document(user_id).collection('medications').stream()
        
        for med in meds:
            data = med.to_dict()
            if today not in data.get("takenTimes", {}):
                med.reference.update({
                    "takenTimes": {today: []},
                    "nextNotification": calculate_next_notification(data["scheduledTimes"])
                })

# 🚀 Procesar notificaciones
def process_notifications(db):
    now = get_local_time()
    current_time_str = now.strftime("%H:%M")
    today = now.strftime("%Y-%m-%d")
    
    users = db.collection('users').stream()
    for user in users:
        user_id = user.id
        user_data = user.to_dict()
        fcm_token = user_data.get('fcmToken')
        
        meds = db.collection('users').document(user_id).collection('medications').stream()
        for med in meds:
            data = med.to_dict()
            if not data.get("enabled", False):
                continue
                
            scheduled_times = data.get("scheduledTimes", [])
            taken_times = data.get("takenTimes", {}).get(today, [])
            
            for time in scheduled_times:
                time_str = f"{time['hour']:02}:{time['minute']:02}"
                scheduled_datetime = now.replace(
                    hour=time["hour"],
                    minute=time["minute"],
                    second=0, microsecond=0
                )
                
                # Notificación a tiempo
                if current_time_str == time_str and time_str not in taken_times:
                    if fcm_token:
                        notify_user(user_id, fcm_token, data["name"], data["dosage"])
                    
                    # Actualizar próxima notificación
                    med.reference.update({
                        "nextNotification": calculate_next_notification(scheduled_times)
                    })
                
                # Notificación de atraso (15 minutos después)
                elif (now - scheduled_datetime).total_seconds() > 900 and time_str not in taken_times:
                    links = db.collection("caregiver_links").where(
                        filter=FieldFilter("patientId", "==", user_id)
                    ).stream()
                    
                    for link in links:
                        caregiver_id = link.to_dict().get("caregiverId")
                        if caregiver_id:
                            notify_caregiver(
                                db, caregiver_id,
                                f"{user_data.get('name', 'Usuario')} NO tomó su medicina ❗",
                                f"{data['name']} debió tomarse a las {time_str}"
                            )

# 🔁 Función principal
def main():
    try:
        print("\n🔵 Iniciando script de recordatorios...")
        initialize_firebase()
        db = firestore.client()
        
        # Migrar datos una vez (opcional)
        # migrate_medication_data(db)
        
        reset_daily_states(db)
        process_notifications(db)
        print("✅ Script completado a las:", get_local_time().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        print(f"❌ Error crítico: {e}")

if __name__ == "__main__":
    main()