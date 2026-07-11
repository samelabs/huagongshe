<?php
!defined('DEBUG') AND exit('Access Denied.');
include '../plugin/zorlan_skycaiji/model/skycaiji.class.php';
skycaiji::init();
$params=skycaiji::get_params();
$installed=skycaiji::installed($params);//检测是否已安装
$type=param(3, 'index');
if($installed){
	//已安装
	$skycaijiUrl='../'.$params['path'];
	include _include(APP_PATH.'plugin/zorlan_skycaiji/view/htm/skycaiji.htm');
}elseif($type=='index'){
	//参数设置
	if($method == 'GET') {
		include _include(APP_PATH.'plugin/zorlan_skycaiji/view/htm/setting.htm');
	} else {
		$return=array('success'=>false,'error'=>'');
		$params=param('params',array(),false);
		if(!preg_match('/^[a-z]+$/',$params['path'])){
			$return['error']='目录名称只能由字母组成！';
		}elseif(!preg_match('/^.{3,15}$/i', $params['user'])){
			$return['error']='用户名长度3-15位';
		}elseif(!preg_match('/^[a-zA-Z0-9\!\@\#\$\%\^\&\*]{6,20}$/i', $params['pwd'])){
			$return['error']='密码长度6-20位';
		}elseif(!preg_match('/^[^\s]+\@([\w\-]+\.){1,}\w+$/i', $params['email'])){
			$return['error']='邮箱格式错误';
		}
		if(!empty($return['error'])){
			skycaiji::echo_json($return);
		}
		skycaiji::set_params($params);//保存参数
		$return['success']=true;
		skycaiji::echo_json($return);
	}
}elseif($type=='install'){
	//开始安装
	$opdo=param('opdo');

	if(empty($opdo)){
		$skycaijiUrl='../'.$params['path'];
		include _include(APP_PATH.'plugin/zorlan_skycaiji/view/htm/install.htm');
	}else{
		$SKYCAIJI_PATH=APP_PATH.$params['path'];//skycaiji目录
		$DOWN_PATH=skycaiji::$rootPath.'data/down/';//文件下载目录
		
		$eachSize=1024*1024;//每块的大小
		$fileUrl='http://down.skycaiji.com/skycaiji.zip';
		
		if($opdo=='files'){
			$fileHeader=get_headers($fileUrl,true);//头信息
			$fileSize=$fileHeader['Content-Length'];//文件大小
			$list=array();
			$count=ceil($fileSize/$eachSize);//块数
			for($i=0;$i<$count;$i++){
				//切割成N份
				$list[$i]=array('id'=>$i+1,'start'=>$i*$eachSize,'end'=>($i+1)*$eachSize);
				if($list[$i]['end']>=$fileSize){
					$list[$i]['end']=$fileSize;
				}
				$list[$i]['end']-=1;//必须减1
			}
			skycaiji::echo_json(array('success'=>true,'size'=>$fileSize,'list'=>$list));
		}elseif($opdo=='down'){
			$fileSize=intval(param('size'));
			$startSize=intval(param('start_size'));
			$endSize=intval(param('end_size'));
			$id=intval(param('fileid'));
		
			$data=array('success'=>false);
			if(file_exists($DOWN_PATH.$id)&&!empty(file_get_contents($DOWN_PATH.$id))){
				//存在文件
				$data['success']=true;
			}else{
				$blockData=skycaiji::get_html($fileUrl,null,"{$startSize}-{$endSize}");//块数据
				$data=array('success'=>false);
				if(empty($blockData)){
					//下载失败
					$data['success']=false;
				}else{
					skycaiji::write_dir_file($DOWN_PATH.$id, $blockData);
					$data['success']=true;
				}
			}
			skycaiji::echo_json($data);
		}elseif($opdo=='bushu'){
			$fileSize=intval(param('size'));
			$count=ceil($fileSize/$eachSize);//块数
			$data=array('success'=>false);
			$is_end=true;//下载完了
			for($i=1;$i<=$count;$i++){
				//判断所有块文件都存在
				if(!file_exists($DOWN_PATH.$i)){
					$is_end=false;
					break;
				}
			}
			if($is_end){
				//下载完成了
				$data['success']=true;
				$allData='';
				for($i=1;$i<=$count;$i++){
					$allData.=file_get_contents($DOWN_PATH.$i);
				}
				skycaiji::write_dir_file($DOWN_PATH.'skycaiji.zip', $allData);

				try {
					$zipClass=new \ZipArchive();//实例化解压类
					if($zipClass->open($DOWN_PATH.'skycaiji.zip')===TRUE){
						$zipClass->extractTo($SKYCAIJI_PATH);
						$zipClass->close();//关闭处理的zip文件
					}else{
						$data['error']='解压失败';
					}
				}catch(\Exception $ex){
					$data['error']='您的服务器不支持ZipArchive解压';
				}
				if(!empty($data['error'])){
					$data['error'].="，请自行将文件{$DOWN_PATH}skycaiji.zip 解压到{$SKYCAIJI_PATH}里";
				}else{
					//解压成功，配置蓝天采集器
					skycaiji::clear_dir($DOWN_PATH);//清空已下载的文件
					$db=$conf['db'][$conf['db']['type']]['master'];//系统配置
					$data['db']=array(
						'db_type'  => 'mysql',
						'db_host'  => $db['host'],
						'db_port'  => 3306,
						'db_name'  => $db['name'],
						'db_pwd'   => $db['password'],
						'db_user'  => $db['user'],
						'db_prefix'  => 'skycaiji_',
						
						'user_name'=>$params['user'],
						'user_pwd'=>$params['pwd'],
						'user_repwd'=>$params['pwd'],
						'user_email'=>$params['email']
					);
				}
			}
			skycaiji::echo_json($data);
		}else{
			exit();
		}
	}
}
?>