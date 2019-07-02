FROM python:3.7

RUN apt-get update

WORKDIR /code

COPY ./requirements.txt ./
RUN pip3 install -r requirements.txt


COPY . .

CMD gunicorn wsgi:app -b 0.0.0.0:5000 -w 2 --timeout 15 --log-level DEBUG

#CMD ["/usr/local/bin/gunicorn", "wsgi:app", "-k", "gthread", "-b", "0.0.0.0:5000", "-w", "2", "--timeout", "15", "--log-level", "DEBUG"]
