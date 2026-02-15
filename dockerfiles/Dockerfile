# Use an official Python runtime as a parent image
# docker build -t werewolves_game .
# docker run -p 5000:5000 --name werewolves_game werewolves_game

FROM python:3.10-slim

WORKDIR /werewolves_game
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip3 install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install gunicorn gevent

COPY templates/ ./templates/
COPY static/ ./static/
COPY app.py config.py  game_engine.py  roles.py .env.werewolves ./
copy img/favicon.ico ./img/

# Expose the port the app runs on
EXPOSE 5000
# Run flaksk app or run through gunicorn for production
#ENV FLASK_APP=app
#CMD ["python", "app.py"]
# OR
#RUN pip install gunicorn eventlet
#CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "-b", "0.0.0.0:5000", "app:app"]
RUN pip install gunicorn gevent
CMD ["gunicorn", "--worker-class", "gevent", "-w", "1", "-b", "0.0.0.0:5000", "app:app"]
