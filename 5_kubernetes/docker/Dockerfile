FROM nginx:alpine

RUN apk add --no-cache gettext

COPY nginx.conf /etc/nginx/nginx.conf
COPY index.template.html /usr/share/nginx/html/index.template.html

CMD ["/bin/sh", "-c", "envsubst '$$POD_NAME' < /usr/share/nginx/html/index.template.html > /usr/share/nginx/html/index.html && nginx -g 'daemon off;'"]
