<?php exit;

function thread_recount($tid) {
	
	// 查找回帖
	$n = post_count(array('tid'=>$tid));
	
	// 对帖子的附件进行检查
	thread_update($tid, array('posts'=>$n));
	
	return $n;
}

?>