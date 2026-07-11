<?php
!defined('DEBUG') AND exit('Forbidden');
$tablepre = $db->tablepre;

try{
  $sql = "ALTER TABLE ".$tablepre."user ADD v CHAR(200) NOT NULL default '0';";
  db_exec($sql);

  $sq2 = "CREATE TABLE IF NOT EXISTS {$tablepre}v_apply (
    `uid` int(11) unsigned NOT NULL COMMENT '用户ID',
    `create_time` bigint(11) unsigned DEFAULT NULL COMMENT '创建时间',
    `v` varchar(255)  DEFAULT NULL COMMENT '认证信息',
    `v_info` varchar(255)  DEFAULT NULL COMMENT '证明信息',
    `v_file` varchar(255)  DEFAULT NULL COMMENT '证明文件',
     `status` int(11) unsigned NOT NULL COMMENT '审核状态0待审核 1成功',
      `remark` varchar(255)  DEFAULT NULL COMMENT '备注，拒绝原因',
    PRIMARY KEY (`uid`)
  ) ENGINE=InnoDB  DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci";
  $r = db_exec($sq2);
  $r === FALSE AND message(-1, '创建签到加V认证审核表结构失败');
}catch(Exception $e){}

$kv = kv_cache_get('iqismart_com_v');
if(!$kv) {
	$kv = array('type'=>'golds', 'count'=>1);
	kv_cache_set('iqismart_com_v', $kv);
}

?>