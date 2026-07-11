<?php 
!defined('DEBUG') AND exit('Forbidden');
$tablepre = $db->tablepre;

$sql = "ALTER TABLE {$tablepre}thread ADD COLUMN thread_keywords char(255) DEFAULT ''";
db_exec($sql);
$sql = "ALTER TABLE {$tablepre}thread ADD COLUMN thread_description char(255) DEFAULT ''";
db_exec($sql);

?>