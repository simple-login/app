FROM python:3.7

WORKDIR /code

# copy everything into /code
COPY . .

# install dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

EXPOSE 7777

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["gunicorn","wsgi:app","-b","0.0.0.0:7777","-w","2","--timeout","15"]
