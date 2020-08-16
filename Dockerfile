# Install npm packages
FROM node:10.17.0-alpine AS npm
WORKDIR /code
COPY ./static/package*.json /code/static/
RUN cd /code/static && npm install


FROM python:3.7
WORKDIR /code

# install some utility packages
RUN apt update && apt install -y vim telnet

# install dependencies
COPY ./requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# copy npm packages
COPY --from=npm /code /code

# copy everything else into /code
COPY . .

EXPOSE 7777

#gunicorn wsgi:app -b 0.0.0.0:7777 -w 2 --timeout 15 --log-level DEBUG
CMD ["gunicorn","wsgi:app","-b","0.0.0.0:7777","-w","2","--timeout","15"]
