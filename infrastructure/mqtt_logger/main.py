''' 
É um observador, apenas usado para passar a telemetria para dentro do container em um formato específico
Assina a telemetria e passa todo o log para o sistema em formato JSON 
'''

# Bibliotecas
import json # Gera e lê mensagens em JSON
import os # Lê variáveis de ambiente 
import time # Gera o timestamp
from paho.mqtt import client as mqtt # Use o MQTT

BROKER = os.getenv("MQTT_HOST", "mosquitto") # Lê o host que está em MQTT, se não tiver usa o mosquitto para passar para MQTT
PORT = int(os.getenv("MQTT_PORT", "1883")) # Lê a porta 1883 e converte para inteiro
TOPIC = os.getenv("MQTT_TOPIC", "observatory/telemetry/#") # Lê o tópico que ele precisa mudar, nesse caso ele lê todos os subtópicos

def on_connect(client, userdata, flags, rc): # Função que é começa quando o cliente usa o broker
    print(json.dumps({"type": "status", "event": "connected", "rc": rc, "topic": TOPIC}), flush=True) # JSON dizendo que conectou, o seu código RC e o tópico 
    client.subscribe(TOPIC, qos=1) # Assina o tópico, manda assinar peo menos uma vez, evita que alguma mensagem seja perdida

def on_message(client, userdata, msg): # Função para quando chega mensagem em MQTT 
    raw = msg.payload.decode("utf-8", errors="replace") # Decodifica a mensagem como texto

    parsed = None # Começa sem conseguir transformar em JSON
    try: # Inicia a tentativa de transformar a mensagem 
        parsed = json.loads(raw) # Tenta converter o texto para objeto Python
    except Exception: # Caso dê erro, ele captura a exceção, registra as mensagens que não são JSON válido para as próxima vezes 
        pass # Ignora o erro e continuar com as próximas mensagens

    event = { # Começa o dicionário do evento 
        "type": "telemetry", # Marca o tipo como telemetry
        "ts": time.time(), # Adiciona o timestamp
        "topic": msg.topic, # Registra o tópico so MQTT 
        "payload_raw": raw, # Guarda o payload como texto bruto 
    } 
    if parsed is not None: # Verifica se o payload foi interpretado como JSON
        event["payload"] = parsed  # Se ele foi, adiciona esse JSON no payload

    print(json.dumps(event, ensure_ascii=False), flush=True) # Imprime o JSON como log no container

client = mqtt.Client() # Cria um cliente MQTT
client.on_connect = on_connect # Registra a função usada ao se conectar 
client.on_message = on_message # Registra a função usada para quando recebe mensagens MQTT
client.connect(BROKER, PORT, keepalive=60) # Conecta ao broker 
client.loop_forever() # Loop infinito do cliente MQTT
