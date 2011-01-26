<?php
function get_users(){
	$ufile = file_get_contents("../users");
	$users = array();
	foreach(explode("\n", $ufile) as $v){
		$v = explode("\t", $v);
		$users[$v[0]] = $v[1];
	}
	return $users;
}
function http_digest_parse($txt)
{
	// protect against missing data
	$needed_parts = array('nonce'=>1, 'nc'=>1, 'cnonce'=>1, 'qop'=>1, 'username'=>1, 'uri'=>1, 'response'=>1);
	$data = array();
	$keys = implode('|', array_keys($needed_parts));

	preg_match_all('@(' . $keys . ')=(?:([\'"])([^\2]+?)\2|([^\s,]+))@', $txt, $matches, PREG_SET_ORDER);

	foreach ($matches as $m) {
		$data[$m[1]] = $m[3] ? $m[3] : $m[4];
		unset($needed_parts[$m[1]]);
	}

	return $needed_parts ? false : $data;
}
function error_die($err){
	header("Content-type: text/json");
	die(json_encode(array("error"=> $err)));
}

function auth(){

	if (empty($_SERVER['PHP_AUTH_DIGEST'])) {
		header('HTTP/1.1 401 Unauthorized');
		header('WWW-Authenticate: Digest realm="CloudCP",qop="auth",nonce="'.uniqid().'",opaque="'.md5("CloudCP upload").'"');
		error_die("Authentication failed");
	}

	// analyze the PHP_AUTH_DIGEST variable
	$users = get_users();
	if (!($data = http_digest_parse($_SERVER['PHP_AUTH_DIGEST'])) || !isset($users[$data['username']])){
		header('HTTP/1.1 401 Unauthorized');
		error_die("Authentication failed");
	}

	$A1 = $users[$data['username']];
	$A2 = md5($_SERVER['REQUEST_METHOD'].':'.$data['uri']);
	$valid_response = md5($A1.':'.$data['nonce'].':'.$data['nc'].':'.$data['cnonce'].':'.$data['qop'].':'.$A2);

	if ($data['response'] != $valid_response){
		header('HTTP/1.1 401 Unauthorized');
		error_die("Authentication failed");
	}
	return $data['username'];
}