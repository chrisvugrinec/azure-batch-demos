#!/bin/bash
rm -f ahn2_05m_int.xml
wget https://geodata.nationaalgeoregister.nl/ahn2/atom/ahn2_05m_int.xml
xpath -q -e '/feed/entry/id | /feed/entry/link[1]' ahn2_05m_int.xml | sed 's/zip\".*/zip/g' | sed 's/<link.*\"//' | sed 's/<id>//' | sed 's/<\/id>//' | sed 's/\n//g'  >anh-files
python init.py
