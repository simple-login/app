FROM python:3.7

WORKDIR /code

# install dependencies
COPY ./requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# copy everything else into /code
COPY . .

EXPOSE 7777

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["gunicorn","wsgi:app","-b","0.0.0.0:7777","-w","2","--timeout","15"]
