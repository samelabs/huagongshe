<?php exit;
// 发帖间隔
if($gid == 101){
	mt_rand(10000,200000);
	usleep(isset($ms));
	$now = time();
	$new = db_find_one('thread',array('uid'=>$uid),array('create_date'=>-1));
	$j = $now - $new['create_date'];
	$j < 60 AND message(-1,"系统设置发帖间隔为1分钟，请稍候重试。");
}
?>