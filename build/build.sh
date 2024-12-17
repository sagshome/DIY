#!/bin/sh


# Local script to rebuild / start everything
echo 'Stopping Services'
python manage.py collectstatic
docker compose down

echo 'Building containers'
docker compose up --build -d



