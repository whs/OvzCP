# DO NOT EDIT!
# THIS FILE WILL BE REPLACED
{% for i in backend %}
backend {{i.name}}{
	set backend.host = "{{i.vm.vz.ip}}";
	set backend.port = "{{i.port}}";
}
{% endfor %}
backend ovzcp{
	set backend.host = "127.0.0.1";
	set backend.port = "21212";
}