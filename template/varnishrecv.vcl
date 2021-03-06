# DO NOT EDIT!
# THIS FILE WILL BE REPLACED
# Generated for varnish {{".".join(version)}}

{% for i in cond -%}
if(req.http.host {% if i.subdomain %}~ "^((.+?)\.|){{i.hostname}}$"{% else %}== "{{i.hostname}}"{%endif%}){
	set req.backend = {{i.backend.name.replace(".", "_")}};
}else 
{%- endfor -%}
if(req.http.host == "{{ovzcphost}}"){
	set req.backend = ovzcp;
	if(req.url ~ "^/static/" && req.url ~ "\?v="){
		unset req.http.cookie;
		return(lookup);
	}
}elseif(req.http.host == "static.{{ovzcphost}}"){
	set req.backend = ovzcp;
	unset req.http.cookie;
	set req.url = "/static" req.url;
	return(lookup);
}{% if nomatch != "None" %}else{
	set req.backend = {{nomatch}};
}{% endif %}
