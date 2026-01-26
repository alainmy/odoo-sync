FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11

WORKDIR /app

COPY ./app /app/app
COPY ./requirements.txt /app/requirements.txt

RUN pip install --upgrade-strategy only-if-needed -r /app/requirements.txt

# Expose port
EXPOSE 5010

# Command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5010"]
