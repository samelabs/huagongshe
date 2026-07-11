<?php 
!defined('DEBUG') AND exit('Forbidden');
$tablepre = $db->tablepre;


$sql = "ALTER TABLE {$tablepre}thread drop column thread_keywords";
db_exec($sql);
$sql = "ALTER TABLE {$tablepre}thread drop column thread_description";
db_exec($sql);
kv_delete('ax_seo');
?>