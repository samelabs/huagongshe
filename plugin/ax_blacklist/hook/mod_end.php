<?php exit;
if($action == 'blacklist') {

	$_uid = param(2, 0);
	
	$method != 'POST' AND message(-1, 'Method error');
	
	$u = user_read($_uid);

	empty($u) AND message(-1, lang('user_not_exists_or_deleted'));
	
	$u['gid'] < 6 AND message(-1, lang('cant_delete_admin_group'));

	user_update($_uid,array('gid'=>7));
	
	// 清理主题帖
	$threadlist = mythread_find_by_uid($_uid, 1, 1000);
	foreach($threadlist as $thread) {
		thread_delete($thread['tid']);
	}
	
	// 清理回帖
	post_delete_by_uid($_uid);
	
	// 清理附件
	attach_delete_by_uid($_uid);

	// 全站统计
	runtime_set('users-', 1);

	//判断限制IP插件是会否存在

	if(is_dir("plugin/xn_ipaccess")){

		ipaccess_inc($u['create_ip'], 'threads',1000);

	}

	message(0, "操作成功");
}
?>