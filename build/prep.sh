#!/bin/sh +x

# get into the happy place
script_dir=`dirname "${0}"`
cd ${script_dir}/..
home=`pwd`
base=`basename $home`


# See if I am really happy
if [ ! -e manage.py ]; then
  echo "Environment does not look right!"
  exit 1
fi

source "${HOME}/${base}_ENV/bin/activate"

# start fresh
rm -fr node_modules
rm -fr static/jquery ; mkdir -p static/jquery
rm -fr static/chart.js ; mkdir static/chart.js
rm -fr static/w3-css ; mkdir static/w3-css
rm -fr static/\@kurkle ; mkdir -p static/\@kurkle/color


npm install jquery   ; cp -R node_modules/jquery/dist/* static/jquery/
npm install chart.js ; cp -R node_modules/chart.js/dist/* static/chart.js/
                       cp -R node_modules/\@kurkle/color/dist/* static/\@kurkle/color/
npm install w3-css   ; cp -R node_modules/w3-css/* static/w3-css/

rm -fr static_root
python manage.py collectstatic



