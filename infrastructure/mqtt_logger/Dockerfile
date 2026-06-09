# Configurações do docker do mqtt_logger
# Lê as mensagens em MQTT e imprime logs JSON
# Usa uma biblioteca Python, define a psta de trabalho no container, copia os requisitos para o conatiner, instala em python, copia o main.py para o container, inicia o main.py quando o container inicia 

FROM python:3.11-slim 
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["python", "main.py"]
