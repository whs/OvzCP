#!/bin/sh
export PYTHONPATH="/opt/ovzcp/Jinja2-2.3-py2.5.egg"
pybabel -v extract -c 'NOTE:' -c '_' -F babel.cfg -o ovzcp.pot ..
for i in th; do 
pybabel update -i ovzcp.pot -d . -l $i
done
