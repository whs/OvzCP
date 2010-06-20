#!/usr/bin/python
import os, sys, time
def readline():
	out = ""
	while True:
		b = sys.stdin.read(1)
		out += b
		if b == "\n": break
		time.sleep(0.01)
	return out

if __name__ == "__main__":
	while True:
		I = readline().strip().split()
		if I[0] in ("start", "stop", "restart"):
			os.system("vzctl "+I[0]+" "+I[1])