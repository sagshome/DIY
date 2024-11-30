#!/bin/bash

echo "Migrate the Database at startup of project"
rm /app/healthcheck
# Wait for few minute and run db migraiton
while ! python manage.py migrate  2>&1; do
   echo "Migration is in progress status"
   sleep 3
done
touch /app/healthcheck
echo "Django docker is fully configured successfully."

exec "$@"