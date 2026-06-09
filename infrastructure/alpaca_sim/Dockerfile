# Define as configurações do docker do simulador -> 
# Cria uma imagem python, instala as dependências, copia o simulador e sobe a API Alpaca para a porta 80

FROM python:3.9-slim 

RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
 