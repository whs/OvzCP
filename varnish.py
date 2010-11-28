import os, ConfigParser, time, sys
sys.path.insert(0, os.path.join(os.getcwd(), "Jinja2-2.3-py2.5.egg"))
import jinja2

_config = ConfigParser.SafeConfigParser()
_config.read("config.ini")

def version(wantInt=True):
	import commands, re
	v=re.findall("\(varnish-(.*?)(?: |\))", commands.getoutput("/usr/sbin/varnishd -V").split("\n")[0])[0].split(".")
	if wantInt:
		return map(lambda x: int(x), v)
	else:
		return v

# Varnish configuration generator
def updateBackend(data):
	jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader("template"))
	ver = version()
	backend = jinja.get_template("varnishbackend.vcl").render(backend=data, prefix=ver[0] < 2, version=map(lambda x: str(x), ver))
	open("sysconf/varnishbackend.vcl", "w").write(backend)
	if version()[0] > 1:
		restart()

def updateRecv(data):
	jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader("template"))
	ver = version()
	recv = jinja.get_template("varnishrecv.vcl").render(cond=data, nomatch=_config.get("varnish", "noMatch"), 
			ovzcphost=_config.get("varnish", "ovzcphost"), prefix=ver[0] < 2, version=map(lambda x: str(x), ver))
	open("sysconf/varnishrecv.vcl", "w").write(recv)
	if version()[0] > 1:
		restart()

def restart():
	import subprocess, commands
	if version()[0] < 2:
		subprocess.Popen("/etc/init.d/varnish restart", shell=True).wait()
		while True:
			if commands.getoutput("pidof varnishd"):
				break
	else:
		return commands.getoutput("/etc/init.d/varnish reload")

if __name__ == "__main__":
	from models import VarnishBackend, VarnishCond
	updateBackend(VarnishBackend.select())
	updateRecv(VarnishCond.select())
	restart()
