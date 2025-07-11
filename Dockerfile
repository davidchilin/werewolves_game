# Use an official Python runtime as a parent image
FROM python:3.10-slim
# Copy files to working directory in the container
WORKDIR /werewolves_game
COPY templates/ app.py favicon.ico requirements.txt /werewolves_game/
COPY templates/ /werewolves_game/templates/
# Install any needed packages specified in requirements.txt
RUN pip3 install --upgrade pip && pip install --no-cache-dir -r requirements.txt
# Expose the port the app runs on
EXPOSE 5000
# Define the command to run the application
ENV FLASK_APP=app
CMD ["python", "app.py"]
#RUN pip install gunicorn
#CMD ["gunicorn", "app:app", "-b", "0.0.0.0:5000", "-w", "8"]
