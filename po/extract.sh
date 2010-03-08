#!/bin/sh
pybabel -v extract -c "NOTE:" -F babel.cfg -o ovzcp.pot ..
for i in th; do 
pybabel update -i ovzcp.pot -d . -l $i
done
