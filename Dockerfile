FROM python:3.7

RUN apt-get update

RUN apt-get install -y vim

WORKDIR /code

COPY ./requirements.txt ./
RUN pip3 install -r requirements.txt


COPY . .

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["gunicorn","wsgi:app","-b","0.0.0.0:7777","-w","2","--timeout","15","--log-level","DEBUG"]

