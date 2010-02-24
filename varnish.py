import os, ConfigParser
try:
	import jinja2
except ImportError:
	import sys
	sys.path.append(os.path.join(os.getcwd(), "Jinja2-2.3-py2.5.egg"))
	import jinja2

_config = ConfigParser.SafeConfigParser()
_config.read("config.ini")

# Varnish configuration generator
def updateBackend(data):
	jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader("template"))
	backend = jinja.get_template("varnishbackend.vcl").render(backend=data)
	open("sysconf/varnishbackend.vcl", "w").write(backend)
	os.system("/etc/init.d/varnish restart")

def updateRecv(data):
	jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader("template"))
	recv = jinja.get_template("varnishrecv.vcl").render(cond=data, nomatch=_config.get("varnish", "noMatch"), ovzcphost=_config.get("varnish", "ovzcphost"))
	open("sysconf/varnishrecv.vcl", "w").write(recv)
	os.system("/etc/init.d/varnish restart")