#!/usr/bin/python
import os
while True:
	try:
		I = raw_input().strip().split()
	except EOFError:
		continue
	if I[0] in ("start", "stop", "restart"):
		os.system("vzctl "+I[0]+" "+I[1])