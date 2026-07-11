<?php exit;
$thread_keywords = param('thread_keywords');
$thread_description = param('thread_description');
db_update('thread', array('tid' => $tid), array('thread_keywords' => $thread_keywords,'thread_description' => $thread_description));	
?>