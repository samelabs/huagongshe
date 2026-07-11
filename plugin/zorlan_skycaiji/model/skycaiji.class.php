<?php
//error_reporting(E_ERROR | E_PARSE);

class skycaiji {
	public static $rootPath;//插件目录
	public static function init(){
		self::$rootPath=dirname(dirname(__FILE__)).'/';
	}
	
	public static function get_html($url, $header=null,$size) {
		$ch = curl_init ();
		curl_setopt ( $ch, CURLOPT_URL, $url );
		curl_setopt ( $ch, CURLOPT_TIMEOUT, 100 );
		curl_setopt ( $ch, CURLOPT_RETURNTRANSFER, 1 );
		curl_setopt ( $ch, CURLOPT_FOLLOWLOCATION, 1 );
		curl_setopt ( $ch, CURLOPT_HEADER, 0 );
		curl_setopt ( $ch, CURLOPT_USERAGENT, "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; SV1; AcooBrowser; .NET CLR 1.1.4322; .NET CLR 2.0.50727)");
	
		//https模式
		curl_setopt ( $ch, CURLOPT_SSL_VERIFYPEER, FALSE );
		curl_setopt ( $ch, CURLOPT_SSL_VERIFYHOST, FALSE );
	
		if (! empty ( $header )) {
			curl_setopt ( $ch, CURLOPT_HTTPHEADER, $header );
		}
		//curl_setopt($ch, CURLOPT_RESUME_FROM, $offset);
		curl_setopt($ch, CURLOPT_RANGE, $size);
	
		$html = curl_exec ( $ch );
		curl_close ( $ch );
		return $html;
	}
	
	/*清空目录，不删除根目录*/
	public static function clear_dir($path,$passFiles=null){
		if(empty($path)){
			return;
		}
		$path=realpath($path);
		if(empty($path)){
			return;
		}
		if(!empty($passFiles)){
			$passFiles=array_map('realpath', $passFiles);
		}
	
		$fileList=scandir($path);
		foreach( $fileList as $file ){
			$fileName=realpath($path.'/'.$file);
			if(is_dir( $fileName ) && '.' != $file && '..' != $file ){
				self::clear_dir($fileName,$passFiles);
				rmdir($fileName);
			}elseif(is_file($fileName)){
				if($passFiles&&in_array($fileName, $passFiles)){
	
	
				}else{
					unlink($fileName);
				}
			}
		}
		clearstatcache();
	}
	
	public static function get_params(){
		$params=include self::$rootPath.'data/params.php';//参数
		$params=is_array($params)?$params:array();
		return $params;
	}
	public static function set_params($params=array()){
		$params=is_array($params)?$params:array();
		$php="<?php\r\nreturn ".var_export($params,true).";\r\n?>";
		self::write_dir_file(self::$rootPath.'data/params.php',$php);//保存参数
	}
	public static function installed($params){
		if(!empty($params)&&file_exists(APP_PATH.$params['path'].'/SkycaijiApp/install/data/install.lock')){
			return true;
		}
		return false;
	}
	/*写入文件*/
	public static function write_dir_file($filename,$data,$flags=null,$content=null){
		$dir = dirname($filename);
		if(!is_dir($dir)){
			mkdir($dir,0777,true);
		}
		return file_put_contents($filename,$data,$flags,$content);
	}
	
	public static function echo_json($data){
		header('Content-Type:application/json; charset=utf-8');
		echo json_encode($data);
		exit();
	}
}
?>