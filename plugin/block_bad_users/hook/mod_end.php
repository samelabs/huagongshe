<?php
exit;
if ($action == 'block') {
    $_uid = param(2, 0);
    $method != 'POST' and message(-1, 'Method error');
	empty($group['allowdeleteuser']) AND message(-1, "无权进行此操作！");
    $u = user_read($_uid);
    empty($u) and message(-1, "此用户不存在！");
    $u['gid'] < 6 and message(-1, "无权管理此用户组会员！");
    $r = user_update($_uid, array('gid' => 7));
	$r === FALSE AND message(-1, "操作失败！");
    message(0, "操作成功！");
}
if ($action == 'unblock') {
    $_uid = param(2, 0);
    $method != 'POST' and message(-1, 'Method error');
	empty($group['allowdeleteuser']) AND message(-1, "无权进行此操作！");
    $u = user_read($_uid);
    empty($u) and message(-1, "此用户不存在！");
    $u['gid'] < 6 and message(-1, "无权管理此用户组会员！");;
    $r = user_update($_uid, array('gid' => 101));
	$r === FALSE AND message(-1, "操作失败！");
    message(0, "操作成功！");
}