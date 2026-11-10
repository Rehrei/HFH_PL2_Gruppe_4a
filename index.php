<?php
declare(strict_types=1);
/**
 * Eine Seite fuer fuenf Versandwege. PHP 8.2+, pdo_mysql, mbstring.
 * Einrichtung: README.md. Alle APIs, HTML, CSS und JS sind hier enthalten.
 * Nur Informationsmails mit genau einem [[LINK]], keine Anhaenge; keine Benutzerverwaltung.
 * Funktionen: Konfiguration, SQL, Rendering, MIME, Queue und Audit.
 * Python liest fertig gerenderten Inhalt aus MariaDB; PHP sendet niemals SMTP.
 */

/** Gemeinsames .env-Format: KEY=VALUE ohne Inline-Kommentare/Interpolation. */
function konfiguration(): array {
    $path = getenv('MAILVERSAND_ENV') ?: '/opt/mailversand/.env';
    if (!$path || !is_readable($path)) throw new RuntimeException('Private Konfiguration fehlt. MAILVERSAND_ENV einrichten.');
    $c = [];
    foreach (file($path, FILE_IGNORE_NEW_LINES) as $line) {
        $line = trim(preg_replace('/^\xEF\xBB\xBF/', '', $line));
        if ($line === '' || str_starts_with($line, '#')) continue;
        if (!str_contains($line, '=')) throw new RuntimeException('Ungültige Konfigurationszeile.');
        [$k, $v] = explode('=', $line, 2); $v = trim($v);
        if (strlen($v) >= 2 && $v[0] === substr($v, -1) && in_array($v[0], ['"', "'"])) $v = substr($v, 1, -1);
        $c[trim($k)] = $v;
    }
    if (!preg_match('/^(?:[A-Za-z][A-Za-z0-9_]*)?$/D', $c['DB_PREFIX'] ?? '')) throw new RuntimeException('Ungültiges Tabellenpräfix.');
    $c['DB_PREFIX'] ??= '';
    return $c;
}

/** Lokale Entwürfe brauchen weder Zugangsdaten noch eine Datenbank. */
function grundwerte(): array {
    return ['DB_PREFIX'=>'', 'MAIL_FROM_ADDR'=>'', 'MAIL_ENVELOPE'=>'',
        'MAIL_SIGNATUR_TEXT'=>'', 'MAIL_TRANSPORT'=>'datei',
        'DB_DOKU_TABELLE'=>'40_maildokumentation', 'DB_BENUTZER_ID'=>'9999',
        'SERVER_VERSAND_AKTIV'=>'false', 'SPERRLISTE_AKTIV'=>'false',
        'VERSAND_STORNO_MINUTEN'=>'5', 'VERSAND_MAX_EMPF_JE_JOB'=>'2000',
        'VERSAND_TEST_PFLICHT'=>'true', 'MAILTO_MAX_LAENGE'=>'1800',
        'MAILTO_BLOCK_GROESSE'=>'30', 'BOUNCE_GRENZE'=>'3'];
}
/** Nur Fehlercodes ausgeben; Treibertexte können SQL, Inhalte und Zugangsdaten enthalten. */
function datenbankfehler(PDOException $e): string {
    $code=(int)($e->errorInfo[1]??0);
    $message=match ($code) {
        1452 => 'Die Fremdschlüsselprüfung verhindert das Speichern. Prüfe, ob DB_BENUTZER_ID (aktuell als Platzhalter 9999 vorgesehen) in der verknüpften Benutzertabelle existiert.',
        1142,1143 => 'Dem MySQL-Benutzer fehlt eine Berechtigung für die angeforderte Operation. Beim Speichern wird INSERT auf der Dokumentationstabelle benötigt.',
        1045 => 'MySQL lehnt die Anmeldung ab. DB_USER, DB_PASS und die Freigabe für den Verbindungshost prüfen.',
        1044 => 'Der MySQL-Benutzer darf nicht auf die konfigurierte Datenbank zugreifen.',
        1054 => 'Ein erwarteter Spaltenname fehlt. Die Dokumentation benötigt mail_id, benutzer_id, betreff, nachricht, versanddatum und empfaengerzahl.',
        1146 => 'Die konfigurierte Tabelle ist in der Datenbank nicht vorhanden. DB_NAME und DB_DOKU_TABELLE prüfen.',
        1364 => 'Eine Pflichtspalte erhält keinen Wert. Zusätzliche Pflichtspalten und AUTO_INCREMENT für mail_id prüfen.',
        1048 => 'Eine Pflichtspalte erhält einen unzulässigen NULL-Wert. Tabellenschema und mögliche Trigger prüfen.',
        1406 => 'Ein Wert ist für die zugehörige Spalte zu lang. Insbesondere betreff (VARCHAR 255) und nachricht (LONGTEXT) prüfen.',
        1366 => 'Ein Wert passt nicht zum Datentyp oder Zeichensatz der Tabelle. Zahlenfelder und UTF-8-Unterstützung prüfen.',
        1062 => 'Ein eindeutiger Schlüssel ist bereits belegt. AUTO_INCREMENT und zusätzliche UNIQUE-Regeln prüfen.',
        2002,2003,2006,2013 => 'Die MySQL-Verbindung konnte nicht hergestellt oder aufrechterhalten werden. Host, Port und Datenbankdienst prüfen.',
        default => 'Die Datenbankoperation ist fehlgeschlagen. Serverprotokoll und Tabellenschema prüfen.',
    };
    $state=(string)($e->errorInfo[0]??$e->getCode());
    $state=preg_match('/^[A-Z0-9]{5}$/D',$state)?$state:'unbekannt';
    return $message.' [SQLSTATE '.$state.', Treibercode '.$code.']';
}
function fehlerprotokoll(Throwable $e): void {
    error_log('Mailversand: '.get_class($e).($e instanceof PDOException?' · '.datenbankfehler($e):' · Zeile '.$e->getLine()));
}
/** Verfügbarkeit getrennt ermitteln; Einrichtungsfehler verhindern kein HTML. */
function vorbereiten(?int $angemeldeteBenutzerId = null): void {
    global $c,$db,$capabilities;
    $c=grundwerte(); $db=null; $issues=[]; $configured=false;
    try {
        $loaded=konfiguration();
        foreach (['VERSAND_STORNO_MINUTEN'=>0,'VERSAND_MAX_EMPF_JE_JOB'=>1,'MAILTO_MAX_LAENGE'=>1,'MAILTO_BLOCK_GROESSE'=>1,'BOUNCE_GRENZE'=>1] as $key=>$min) {
            if (isset($loaded[$key]) && (!ctype_digit($loaded[$key]) || (int)$loaded[$key]<$min)) throw new RuntimeException('Ungültiger Grenzwert in der Konfiguration.');
        }
        $c=array_replace($c,$loaded);
        if ($angemeldeteBenutzerId !== null) {
            $c['DB_BENUTZER_ID'] = (string)$angemeldeteBenutzerId;
        }
        dokumentationstabelle();
        if (!preg_match('/^[1-9][0-9]{0,9}$/D',$c['DB_BENUTZER_ID']) || (int)$c['DB_BENUTZER_ID']>2147483647) throw new RuntimeException('Ungültige Benutzer-ID.');
        $configured=true;
    } catch (Throwable $e) {
        $issues[]='Konfiguration fehlt oder ist ungültig. Lokale Entwürfe verwenden Standardwerte ohne konfigurierte Signatur.';
    }
    $serverTables=false; $blocklist=false;
    if ($configured) {
        try {
            foreach (['SERVER_VERSAND_AKTIV','SPERRLISTE_AKTIV'] as $key)
                if (!in_array($c[$key],['true','false'],true)) throw new RuntimeException('Ungültiger Optionswert.');
            foreach (['DB_HOST','DB_PORT','DB_NAME','DB_USER','DB_PASS'] as $key) if (!array_key_exists($key,$c)) throw new RuntimeException('Datenbankkonfiguration unvollständig.');
            $db=new PDO('mysql:host='.$c['DB_HOST'].';port='.$c['DB_PORT'].';dbname='.$c['DB_NAME'].';charset=utf8mb4',$c['DB_USER'],$c['DB_PASS'],[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION,PDO::ATTR_EMULATE_PREPARES=>false,PDO::ATTR_DEFAULT_FETCH_MODE=>PDO::FETCH_ASSOC,PDO::ATTR_TIMEOUT=>2]);
            $db->exec("SET time_zone = '+00:00'");
            sql('SELECT `mail_id`,`benutzer_id`,`betreff`,`nachricht`,`versanddatum`,`empfaengerzahl` FROM '.dokumentationstabelle().' LIMIT 0');
        } catch (Throwable $e) {
            fehlerprotokoll($e);
            $db=null;
            $issues[]='Datenbank oder Dokumentationstabelle nicht verfügbar. Tabellenname, Spalten und Zugangsdaten prüfen.';
        }
        if ($db && $c['SERVER_VERSAND_AKTIV']==='true') {
            try {
                foreach (['job','empfaenger','queue','sperre','log'] as $table) sql('SELECT * FROM {p}'.$table.' LIMIT 0');
                $serverTables=true;
            } catch (Throwable $e) { $issues[]='Optionale Serverversandtabellen fehlen. worker.py init-server ausführen.'; }
        }
        if ($db && ($c['SPERRLISTE_AKTIV']==='true' || $serverTables)) {
            try { sql('SELECT email,abgemeldet,bounce_count FROM {p}sperre LIMIT 0'); $blocklist=true; }
            catch (Throwable $e) { $issues[]='Die aktivierte Sperrliste ist nicht verfügbar. Übergaben bleiben bis zur Einrichtung gesperrt.'; }
        }
    }
    $sender=$configured && filter_var($c['MAIL_FROM_ADDR'],FILTER_VALIDATE_EMAIL) && filter_var($c['MAIL_ENVELOPE'],FILTER_VALIDATE_EMAIL);
    $transport=$configured && in_array($c['MAIL_TRANSPORT'],['datei','submission','relay'],true);
    if ($c['SERVER_VERSAND_AKTIV']==='true' && (!$sender || !$transport)) $issues[]='Absender oder Transport nicht vollständig konfiguriert. Serverversand ist nicht verfügbar.';
    if (!$db) $issues[]='Lokale Mailentwürfe sind verfügbar; Übergaben werden derzeit nicht dokumentiert.';
    $capabilities=['database'=>$db!==null,'server'=>$db!==null && $serverTables && (bool)$sender && $transport,
        'blocklist'=>$blocklist,'hinweise'=>$issues];
}

/** HTML immer escapen; Vorschau und Mail teilen sich dasselbe Rendering. */
function h(string $s): string { return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
/** Headerwerte ohne CR/LF; die Formulareingabe wird zusätzlich strikt geprüft. */
function headerwert(string $s): string { return str_replace(["\r", "\n"], '', $s); }
/** SQL-Präfix nur aus validierter Konfiguration, sämtliche Werte gebunden. */
function sql(string $s, array $args = []): PDOStatement {
    global $db, $c;
    $q = $db->prepare(str_replace('{p}', $c['DB_PREFIX'], $s)); $q->execute($args); return $q;
}
/** Eigenständiger Tabellenname: führende Ziffern erlaubt, immer als Identifier quotiert. */
function dokumentationstabelle(): string {
    global $c;
    $name=$c['DB_DOKU_TABELLE'];
    if (!preg_match('/^[A-Za-z0-9_]{1,64}$/D',$name)) throw new RuntimeException('Ungültiger Dokumentationstabellenname.');
    return '`'.$name.'`';
}
/** Statische Benutzer-ID ist ein Platzhalter, keine Anmeldung. Sitzung schützt die Ansicht. */
function dokumentationsbereich(): string {
    global $c;
    return hash('sha256',json_encode([$c['DB_HOST']??'',$c['DB_PORT']??'',$c['DB_NAME']??'',
        $c['DB_DOKU_TABELLE'],$c['DB_BENUTZER_ID']],JSON_THROW_ON_ERROR));
}
/** Neueste fünf Dokumentationen der konfigurierten Benutzer-ID, sitzungsunabhängig. */
function dokumentationsliste(): array {
    global $c;
    return sql("SELECT CONCAT('d',mail_id) AS id,betreff,'mailprogramm' AS weg,'dokumentiert' AS status,
        versanddatum,NULL AS senden_ab,UTC_TIMESTAMP() AS jetzt,`empfaengerzahl` AS anzahl,
        0 AS gesendet,0 AS datei,0 AS fehler FROM ".dokumentationstabelle()."
        WHERE benutzer_id=? ORDER BY versanddatum DESC,mail_id DESC LIMIT 5",[$c['DB_BENUTZER_ID']])->fetchAll();
}
/** Ein Ereignis pro Snapshot-Empfänger; Protokoll ist unabhängig vom Job-Löschen. */
function protokoll(int $job, string $event, array $emails, string $detail = ''): void {
    global $context;
    foreach ($emails as $email) sql('INSERT INTO {p}log(job_id,benutzer,empfaenger,ereignis,detail) VALUES(?,?,?,?,?)', [$job,$context,$email,$event,$detail]);
}
/** Prüft Klartext, Link und Adressen, filtert Dubletten und Sperrliste serverseitig. */
function nachricht(array $in): array {
    global $c,$db,$capabilities;
    if ($c['SPERRLISTE_AKTIV']==='true' && !$capabilities['blocklist']) throw new RuntimeException('Die aktivierte Sperrliste ist nicht verfügbar.');
    foreach (['betreff','text','url','label','emails'] as $key) if (!isset($in[$key]) || !is_string($in[$key])) throw new InvalidArgumentException('Bitte alle Felder ausfüllen.');
    $subject = trim($in['betreff']); $text = str_replace(["\r\n","\r"], "\n", trim($in['text']));
    $url = trim($in['url']); $label = trim($in['label']);
    if ($subject === '' || mb_strlen($subject) > 255 || preg_match('/[\x00-\x1F\x7F]/', $subject)) throw new InvalidArgumentException('Betreff fehlt, ist zu lang oder enthält Steuerzeichen.');
    if (strlen($text) > 50000 || substr_count($text, '[[LINK]]') !== 1 || str_contains($text, '[[ANREDE]]')) throw new InvalidArgumentException('Text: genau einmal [[LINK]], höchstens 50.000 Bytes. Individuelle Anreden werden hier nicht verwendet.');
    if (!filter_var($url, FILTER_VALIDATE_URL) || !in_array(strtolower(parse_url($url, PHP_URL_SCHEME) ?? ''), ['http','https']) || strlen($url)>1000 || preg_match('/[\x00-\x20]/', $url)) throw new InvalidArgumentException('Bitte einen gültigen HTTP-/HTTPS-Link eintragen.');
    if ($label === '' || mb_strlen($label)>160 || preg_match('~https?://|www\.~i', $text . $label)) throw new InvalidArgumentException('Linkbeschriftung fehlt/ist zu lang oder der Text enthält einen zusätzlichen Link.');
    $raw = preg_split('/[\s;,]+/', trim($in['emails']), -1, PREG_SPLIT_NO_EMPTY);
    if (count($raw)>10000) throw new InvalidArgumentException('Zu viele Adressangaben.');
    $emails = []; $duplicates = 0; $blocked = 0;
    foreach ($raw as $address) {
        if (strlen($address)>254 || !filter_var($address,FILTER_VALIDATE_EMAIL) || preg_match('/[^\x21-\x7E]/', $address)) throw new InvalidArgumentException('Ungültige E-Mail-Adresse: '.$address);
        $address = strtolower($address);
        if (isset($emails[$address])) { $duplicates++; continue; }
        $emails[$address] = true;
    }
    if ($capabilities['blocklist']) foreach (array_keys($emails) as $address) {
        if (sql('SELECT email FROM {p}sperre WHERE email=? AND (abgemeldet=1 OR bounce_count>=?)', [$address,(int)$c['BOUNCE_GRENZE']])->fetch()) { unset($emails[$address]); $blocked++; }
    }
    $emails = array_keys($emails); sort($emails);
    if (!$emails || count($emails)>(int)$c['VERSAND_MAX_EMPF_JE_JOB']) throw new InvalidArgumentException('Keine freigegebenen Empfänger oder Empfängerobergrenze überschritten.');
    $signature = $c['MAIL_SIGNATUR_TEXT'] ?? '';
    $plain = str_replace('[[LINK]]', $label.' ('.$url.')', $text).($signature !== '' ? "\n\n".$signature : '');
    $html = '<p>'.nl2br(str_replace('[[LINK]]','<a href="'.h($url).'">'.h($label).'</a>',h($text)),false).'</p>';
    if ($signature !== '') $html .= '<p>'.nl2br(h($signature),false).'</p>';
    $fingerprint = hash('sha256', json_encode([$subject,$plain,$html,$emails,$c],JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR));
    return compact('subject','plain','html','emails','fingerprint','duplicates','blocked')+['sperrliste_geprueft'=>$capabilities['blocklist']];
}

/** RFC-2047-Faltung verhindert überlange Header bei Umlauten. */
function encoded(string $s): string { return mb_encode_mimeheader(headerwert($s),'UTF-8','B',"\r\n"); }
/** EML: CRLF, BCC, multipart/alternative; X-Unsent als Entwurfshinweis für Outlook. */
function eml(array $m, string $way): string {
    $boundary = 'mail_'.bin2hex(random_bytes(16));
    // Kein festes From im Cliententwurf: Benutzer wählt sein lokales Konto.
    $headers = ['To: undisclosed-recipients:;', 'Bcc: '.implode(",\r\n ", $m['emails']), 'Subject: '.encoded($m['subject'])];
    if (in_array($way,['outlook_alt','outlook_neu'],true)) $headers[] = 'X-Unsent: 1';
    $headers[] = 'MIME-Version: 1.0'; $headers[] = 'Content-Type: multipart/alternative; boundary="'.$boundary.'"';
    $body = '';
    foreach (['plain'=>'plain','html'=>'html'] as $key=>$type) {
        $value = preg_replace('/\r\n|\r|\n/', "\r\n", $m[$key]);
        $body .= '--'.$boundary."\r\nContent-Type: text/$type; charset=UTF-8\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n".quoted_printable_encode($value)."\r\n";
    }
    return implode("\r\n",$headers)."\r\n\r\n".$body.'--'.$boundary."--\r\n";
}
/** Mailto-URLs werden nach tatsächlicher kodierter Länge UND Empfängerzahl geteilt. */
function bloecke(array $m): array {
    global $c; $blocks=[]; $current=[];
    $url = fn($e) => 'mailto:?bcc='.rawurlencode(implode(',',$e)).'&subject='.rawurlencode($m['subject']);
    foreach ($m['emails'] as $email) {
        $candidate = [...$current,$email];
        if (count($candidate)>(int)$c['MAILTO_BLOCK_GROESSE'] || strlen($url($candidate))>(int)$c['MAILTO_MAX_LAENGE']) {
            if (!$current) throw new InvalidArgumentException('Betreff oder Adresse zu lang für mailto. Bitte Betreff kürzen.');
            $blocks[] = ['url'=>$url($current),'emails'=>$current]; $current=[];
        }
        $current[]=$email;
        if (strlen($url($current))>(int)$c['MAILTO_MAX_LAENGE']) throw new InvalidArgumentException('Betreff zu lang für mailto.');
    }
    if ($current) $blocks[]=['url'=>$url($current),'emails'=>$current];
    return $blocks;
}

/** Alle Mailclient-Wege erhalten eine EML und dieselbe Mailto-Alternative. */
function clientantwort(array $m, string $way): array {
    $out=['eml'=>base64_encode(eml($m,$way)),'emails'=>$m['emails'],'plain'=>$m['plain'],'html'=>$m['html']];
    try { $out['blocks']=bloecke($m); }
    catch (InvalidArgumentException $e) { $out['mailto_fehler']=$e->getMessage(); }
    return $out;
}

/** Job + Empfänger-Snapshot + optionale Queue werden innerhalb einer Transaktion angelegt. */
function job(array $m, string $way, string $request, ?int $test = null): int {
    global $context,$c,$db;
    $server = in_array($way,['smtp','test']);
    $status = $server ? 'laeuft' : 'uebergeben';
    $delay = $way==='test' ? 0 : max(0,(int)$c['VERSAND_STORNO_MINUTEN']);
    sql('INSERT INTO {p}job(benutzer,betreff,body_text,body_html,fingerprint,weg,transport,status,test_job,senden_ab,request_id) VALUES(?,?,?,?,?,?,?,?,?,DATE_ADD(UTC_TIMESTAMP(),INTERVAL ? MINUTE),?)',
        [$context,$m['subject'],$m['plain'],$m['html'],$m['fingerprint'],$way,$c['MAIL_TRANSPORT'],$status,$test,$delay,$request]);
    $id=(int)$db->lastInsertId();
    foreach ($m['emails'] as $email) {
        sql('INSERT INTO {p}empfaenger(job_id,email) VALUES(?,?)',[$id,$email]);
        if ($server) sql('INSERT INTO {p}queue(job_id,email,message_id) VALUES(?,?,?)',[$id,$email,'<'.bin2hex(random_bytes(16)).'@'.explode('@',$c['MAIL_FROM_ADDR'])[1].'>']);
    }
    protokoll($id,'job_erstellt',$m['emails']);
    if (!$server) protokoll($id,'uebergeben',$m['emails'],'An Browser bereitgestellt; kein Versandnachweis');
    return $id;
}

/** Sechs vorhandene Pflichtspalten, keine Erweiterung oder Metadaten im Nachrichtentext. */
function dokumentieren(array $m, string $way, string $request): array {
    global $db,$c;
    $scope=dokumentationsbereich();
    $cache=&$_SESSION['mail_dokumentation'][$scope];
    if (!is_array($cache)) $cache=[];
    // Die PHP-Sitzungssperre serialisiert Wiederholungen derselben Browsersitzung.
    // Ohne request_id-Spalte ist dies kein dauerhafter datenbankweiter Duplikatschutz.
    if (isset($cache[$request])) {
        if (!hash_equals($cache[$request]['fingerprint'],$m['fingerprint'])) throw new InvalidArgumentException('Inhalt geändert. Bitte eine neue Vorschau erstellen.');
        $id=$cache[$request]['id'];
        $exists=sql('SELECT `mail_id` FROM '.dokumentationstabelle().' WHERE `mail_id`=? AND `benutzer_id`=?',[$id,$c['DB_BENUTZER_ID']])->fetch();
        if (!$exists) throw new RuntimeException('Dokumentation nicht mehr vorhanden. Bitte eine neue Vorschau erstellen.');
    } else {
        // Vor dem INSERT rendern, damit ein fehlerhafter Entwurf keinen Eintrag erzeugt.
        $rendered=clientantwort($m,$way);
        sql('INSERT INTO '.dokumentationstabelle().' (`benutzer_id`,`betreff`,`nachricht`,`versanddatum`,`empfaengerzahl`) VALUES(?,?,?,UTC_TIMESTAMP(),?)',
            [$c['DB_BENUTZER_ID'],$m['subject'],$m['plain'],count($m['emails'])]);
        $id=(int)$db->lastInsertId();
        $cache[$request]=['id'=>$id,'fingerprint'=>$m['fingerprint']];
        // Keine Inhalte/Empfänger in der Sitzung; nur begrenzt Kennungen speichern.
        if (count($cache)>300) array_shift($cache);
    }
    $rendered??=clientantwort($m,$way);
    return ['id'=>'d'.$id]+$rendered;
}

function dokumentationsaktion(string $action, array $in): array {
    global $c;
    if ($action!=='protokoll') throw new InvalidArgumentException('Das vorhandene Tabellenschema unterstützt keine Versandbestätigung oder Empfängersuche.');
    if (!preg_match('/^d([1-9][0-9]*)$/D',(string)($in['id']??''),$match) || !in_array('d'.$match[1],array_column(dokumentationsliste(),'id'),true)) throw new InvalidArgumentException('Der Eintrag gehört nicht zu den letzten fünf Dokumentationen dieser Benutzer-ID. Bitte die Liste aktualisieren.');
    $row=sql('SELECT `mail_id`,`betreff`,`nachricht`,`versanddatum`,`empfaengerzahl` FROM '.dokumentationstabelle().' WHERE `mail_id`=? AND `benutzer_id`=?',[$match[1],$c['DB_BENUTZER_ID']])->fetch();
    if (!$row) throw new InvalidArgumentException('Dokumentation nicht mehr vorhanden.');
    return ['log'=>[['job_id'=>'d'.$row['mail_id'],'zeit'=>$row['versanddatum'],'empfaenger'=>null,
        'ereignis'=>'uebergabe_dokumentiert','detail'=>$row['betreff'].' · '.$row['empfaengerzahl']." Empfänger\n".$row['nachricht']]]];
}

try {
    if (session_status()!==PHP_SESSION_ACTIVE) session_start(['cookie_httponly'=>true,'cookie_secure'=>!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS']!=='off','cookie_samesite'=>'Strict','use_strict_mode'=>true]);
    $angemeldeteBenutzerId = null;
    /*
     * Integrationspunkt für die Anmeldung der Hauptanwendung.
     * Vor dem Aktivieren deren Authentifizierungsprüfung einbinden und den
     * Sitzungsschlüssel unten anpassen. Die Hauptanwendung muss den aktiven
     * Benutzer und die Mailversand-Berechtigung für diesen Aufruf prüfen.
     * Die ID darf nur aus der serverseitig geprüften Sitzung stammen.
     *
    $sitzungsId = $_SESSION['auth']['benutzer_id'] ?? null;
    $angemeldeteBenutzerId = (is_int($sitzungsId) || is_string($sitzungsId))
        ? filter_var($sitzungsId, FILTER_VALIDATE_INT, ['options'=>['min_range'=>1,'max_range'=>2147483647]])
        : false;
    if ($angemeldeteBenutzerId === false) {
        http_response_code(401);
        throw new RuntimeException('Bitte melde dich in der Hauptanwendung an.');
    }
    */
    vorbereiten($angemeldeteBenutzerId);
    // Technischer Sitzungskontext für optionale Serveraufträge.
    $_SESSION['mail_context'] ??= 'session:'.bin2hex(random_bytes(24));
    $context = $_SESSION['mail_context'];
    $_SESSION['mail_csrf'] ??= bin2hex(random_bytes(32));
    $nonce=base64_encode(random_bytes(18));
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    header('Referrer-Policy: no-referrer');
    header("Content-Security-Policy: default-src 'none'; script-src 'nonce-$nonce'; style-src 'nonce-$nonce'; connect-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'");
    if ($_SERVER['REQUEST_METHOD']==='POST') {
        header('Content-Type: application/json; charset=utf-8');
        if ((int)($_SERVER['CONTENT_LENGTH']??0)>262144) throw new InvalidArgumentException('Anfrage zu groß.');
        $in=json_decode(file_get_contents('php://input'),true,512,JSON_THROW_ON_ERROR);
        if (!is_array($in) || !is_string($in['csrf']??null) || !hash_equals($_SESSION['mail_csrf'], $in['csrf'])) { http_response_code(403); throw new InvalidArgumentException('Sitzung abgelaufen. Seite neu laden.'); }
        $action=$in['action']??''; $out=[];
        if (in_array($action,['test','smtp'],true) && !$capabilities['server']) { http_response_code(503); throw new RuntimeException('Serverversand benötigt eine gültige Konfiguration und eine verfügbare Datenbank.'); }
        if (in_array($action,['suche','abbrechen','bestaetigen','protokoll'],true) && !$db) { http_response_code(503); throw new RuntimeException('Diese Funktion benötigt eine verfügbare Datenbank.'); }
        if ($action==='status' && !$db) {
            $out=['jobs'=>[],'user'=>$context];
        } elseif ($action==='suche') {
            if (!$capabilities['server']) throw new InvalidArgumentException('Die Dokumentation speichert nur die Empfängerzahl, keine einzelnen Adressen.');
            $email=strtolower(trim($in['email']??''));
            if (!filter_var($email,FILTER_VALIDATE_EMAIL)) throw new InvalidArgumentException('Bitte eine gültige Suchadresse eingeben.');
            $out['log']=sql('SELECT l.job_id,l.zeit,l.empfaenger,l.ereignis,l.detail FROM {p}log l JOIN {p}job j ON j.id=l.job_id WHERE j.benutzer=? AND l.empfaenger=? ORDER BY l.id DESC LIMIT 300',[$context,$email])->fetchAll();
        } elseif (in_array($action,['bestaetigen','protokoll','abbrechen'],true) && str_starts_with((string)($in['id']??''),'d')) {
            $out=dokumentationsaktion($action,$in);
        } elseif ($action==='status') {
            $jobs=dokumentationsliste();
            foreach ($jobs as &$entry) $entry['benutzer']=$context;
            unset($entry);
            if ($capabilities['server']) $jobs=array_merge($jobs,sql("SELECT j.id,j.benutzer,j.betreff,j.weg,j.status,j.senden_ab,UTC_TIMESTAMP() AS jetzt,
                (SELECT COUNT(*) FROM {p}empfaenger e WHERE e.job_id=j.id) AS anzahl,
                (SELECT COUNT(*) FROM {p}queue q WHERE q.job_id=j.id AND q.status='gesendet') AS gesendet,
                (SELECT COUNT(*) FROM {p}queue q WHERE q.job_id=j.id AND q.status='datei') AS datei,
                (SELECT COUNT(*) FROM {p}queue q WHERE q.job_id=j.id AND q.status IN ('fehler','unklar','gesperrt')) AS fehler
                FROM {p}job j WHERE j.benutzer=? ORDER BY j.id DESC LIMIT 30",[$context])->fetchAll());
            $out=['jobs'=>$jobs,'user'=>$context];
        } elseif (in_array($action,['abbrechen','bestaetigen','protokoll'])) {
            if (!$capabilities['server']) throw new RuntimeException('Optionale Serveraufträge sind nicht aktiviert.');
            $id=(int)($in['id']??0); $db->beginTransaction();
            $j=sql('SELECT *,UTC_TIMESTAMP() AS jetzt FROM {p}job WHERE id=? FOR UPDATE',[$id])->fetch();
            if (!$j || $j['benutzer']!==$context) throw new InvalidArgumentException('Kein Zugriff auf diesen Auftrag in dieser Sitzung.');
            $addresses=sql('SELECT email FROM {p}empfaenger WHERE job_id=?',[$id])->fetchAll(PDO::FETCH_COLUMN);
            if ($action==='abbrechen') {
                if ($j['status']!=='wartet_freigabe' && !($j['status']==='laeuft' && $j['senden_ab']>$j['jetzt'] && $j['weg']==='smtp')) throw new InvalidArgumentException('Stornofenster ist geschlossen.');
                sql("UPDATE {p}job SET status='abgebrochen' WHERE id=?",[$id]);
                sql("UPDATE {p}queue SET status='abgebrochen',fertig_am=UTC_TIMESTAMP() WHERE job_id=? AND status='offen'",[$id]);
                protokoll($id,'abgebrochen',$addresses);
            } elseif ($action==='bestaetigen') {
                if ($j['status']!=='uebergeben') throw new InvalidArgumentException('Nur Clientübergaben können bestätigt werden.');
                sql("UPDATE {p}job SET status='bestaetigt' WHERE id=?",[$id]); protokoll($id,'benutzer_bestaetigt',$addresses,'Aussage des Benutzers, kein Versandnachweis');
            } else {
                $email=trim($in['email']??'');
                $out['log']=sql('SELECT zeit,empfaenger,ereignis,detail FROM {p}log WHERE job_id=? AND (?=\'\' OR empfaenger=?) ORDER BY id DESC LIMIT 300',[$id,$email,strtolower($email)])->fetchAll();
            }
            $db->commit();
        } elseif (in_array($action,['vorschau','outlook_alt','outlook_neu','thunderbird','apple_mail','test','smtp'])) {
            $m=nachricht($in);
            if ($action==='vorschau') $out=$m;
            elseif (!$db && in_array($action,['outlook_alt','outlook_neu','thunderbird','apple_mail'],true)) {
                $out=['id'=>null,'lokal'=>true];
                $out+=clientantwort($m,$action);
            } elseif (in_array($action,['outlook_alt','outlook_neu','thunderbird','apple_mail'],true)) {
                $request=$in['request']??'';
                if (!is_string($request) || !preg_match('/^[a-f0-9]{64}$/D',$request)) throw new InvalidArgumentException('Ungültige Anfragenkennung.');
                $out=dokumentieren($m,$action,hash('sha256',$context.$action.$request));
            } else {
                $testEmail = strtolower(trim(is_string($in['test_email']??null)?$in['test_email']:''));
                if (($action==='test' || ($action==='smtp' && $c['VERSAND_TEST_PFLICHT']==='true')) && !filter_var($testEmail,FILTER_VALIDATE_EMAIL)) throw new InvalidArgumentException('Bitte eine gültige Testadresse eingeben.');
                $request=$in['request']??'';
                if (!is_string($request) || !preg_match('/^[a-f0-9]{64}$/D',$request)) throw new InvalidArgumentException('Ungültige Anfragenkennung.');
                $request=hash('sha256',$context.$action.$request);
                $db->beginTransaction();
                $existing=sql('SELECT * FROM {p}job WHERE request_id=?',[$request])->fetch();
                if ($existing) {
                    $out=['id'=>(int)$existing['id'],'duplicate'=>true];
                    // Bei verlorener Browserantwort den gespeicherten Entwurf erneut liefern.
                    if (in_array($action,['outlook_alt','outlook_neu','thunderbird','apple_mail'])) {
                        $saved=['subject'=>$existing['betreff'],'plain'=>$existing['body_text'],'html'=>$existing['body_html'],
                            'emails'=>sql('SELECT email FROM {p}empfaenger WHERE job_id=? ORDER BY email',[$existing['id']])->fetchAll(PDO::FETCH_COLUMN)];
                        if ($action==='outlook_neu') $out+=['blocks'=>bloecke($saved),'html'=>$saved['html'],'plain'=>$saved['plain']];
                        else $out+=['eml'=>base64_encode(eml($saved,$action)),'emails'=>$saved['emails']];
                    }
                    $db->commit();
                }
                else {
                    $test=null;
                    if ($action==='smtp' && $c['VERSAND_TEST_PFLICHT']==='true') {
                        $testRow=sql("SELECT j.id FROM {p}job j JOIN {p}queue q ON q.job_id=j.id WHERE j.benutzer=? AND j.weg='test' AND j.fingerprint=? AND j.transport=? AND q.email=? AND q.status=? ORDER BY j.id DESC LIMIT 1",[$context,$m['fingerprint'],$c['MAIL_TRANSPORT'],$testEmail,$c['MAIL_TRANSPORT']==='datei'?'datei':'gesendet'])->fetch();
                        if (!$testRow) throw new InvalidArgumentException('Zuerst Testmail für diesen unveränderten Inhalt und diese Empfänger erfolgreich abarbeiten lassen.');
                        $test=(int)$testRow['id'];
                    }
                    $blocks=$action==='outlook_neu'?bloecke($m):[];
                    if ($action==='test') $m['emails']=[$testEmail];
                    $id=job($m,$action,$request,$test);
                    if ($action==='test') protokoll($id,'testmail',$m['emails'],'In Warteschlange; noch nicht versendet');
                    $out=['id'=>$id];
                    if ($action==='outlook_neu') $out+=['blocks'=>$blocks,'html'=>$m['html'],'plain'=>$m['plain']];
                    elseif (in_array($action,['outlook_alt','thunderbird','apple_mail'])) $out+=['eml'=>base64_encode(eml($m,$action)),'emails'=>$m['emails']];
                    $db->commit();
                }
            }
        } else throw new InvalidArgumentException('Unbekannte Aktion.');
        echo json_encode(['ok'=>true,'capabilities'=>$capabilities]+$out,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR); exit;
    }
} catch (Throwable $e) {
    if (isset($db) && $db->inTransaction()) $db->rollBack();
    fehlerprotokoll($e);
    $safe=$e instanceof PDOException ? datenbankfehler($e) : ($e instanceof InvalidArgumentException || $e instanceof RuntimeException ? $e->getMessage() : 'PHP-Fehler beim Verarbeiten der Übergabe. Serverprotokoll prüfen.');
    if (http_response_code()<400) http_response_code($e instanceof InvalidArgumentException ? 400 : 500);
    if (($_SERVER['REQUEST_METHOD']??'GET')==='POST') { header('Content-Type: application/json; charset=utf-8'); echo json_encode(['ok'=>false,'error'=>$safe,'capabilities'=>$capabilities??null]); }
    else { header('Content-Type: text/html; charset=utf-8'); echo '<!doctype html><html lang="de"><meta charset="utf-8"><title>Mailversand einrichten</title><h1>Mailversand</h1><p>'.h($safe).'</p></html>'; }
    exit;
}
header('Content-Type: text/html; charset=utf-8');
?>
<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mail verfassen</title>
<style nonce="<?=h($nonce)?>">
:root{font-family:Segoe UI,system-ui,sans-serif;color:#192c39;background:#f0f3f4;color-scheme:light}*{box-sizing:border-box}body{margin:0}main{max-width:1140px;margin:auto;padding:32px 24px}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}h1{font-size:28px;margin:5px 0}h2{font-size:18px;margin:0 0 12px}.eyebrow{font-size:12px;letter-spacing:.14em;font-weight:700;color:#537078}.user{font-size:14px;color:#51646d}.grid{display:grid;grid-template-columns:1.15fr 1fr;gap:22px}.card{background:white;border:1px solid #dce3e5;border-radius:14px;padding:24px;margin-bottom:20px}label{display:block;font-size:14px;font-weight:600;margin:17px 0 7px}input,textarea,select{font:inherit;width:100%;border:1px solid #b8c7cd;border-radius:7px;padding:11px;background:#fcfdfd}textarea{resize:vertical;line-height:1.5}button,.button{font:inherit;font-size:14px;font-weight:600;border:1px solid #b7c8cc;border-radius:7px;padding:11px 14px;background:white;color:#203e48;cursor:pointer;display:inline-block;text-decoration:none}button:hover,.button:hover{background:#eaf2f1}button:disabled{opacity:.45;cursor:not-allowed}.primary{background:#146a64;color:white;border-color:#146a64}.primary:hover{background:#10534f}.danger{color:#ac2937;border-color:#dcb1b5}.buttons{display:flex;flex-wrap:wrap;gap:9px;margin-top:14px}.hint{font-size:13px;line-height:1.55;color:#5a6d76;margin:8px 0}.line{border:0;border-top:1px solid #e1e7e9;margin:22px 0}.badge{background:#e7f1ed;color:#24645c;padding:5px 9px;border-radius:5px;font-size:12px}.notice{padding:13px 16px;border-left:4px solid #146a64;background:#e7f1ef;margin-bottom:18px;white-space:pre-wrap}.error{border-color:#b53341;background:#fff0f0}iframe{border:1px solid #e1e7e9;border-radius:7px;width:100%;height:220px;background:white}details summary{cursor:pointer;font-weight:600}table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;vertical-align:top;padding:10px 6px;border-bottom:1px solid #e1e7e9}td button{padding:6px 8px;font-size:12px;margin:3px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 Consolas,monospace}.scroll{overflow:auto}#fallback{min-height:140px}a:focus-visible,button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid #d1a34a;outline-offset:3px}[hidden]{display:none!important}@media(max-width:780px){.grid{grid-template-columns:1fr}main{padding:22px 14px}.card{padding:18px}header{align-items:flex-start;gap:12px}.user{max-width:45%;overflow-wrap:anywhere}}
</style></head><body><main>
<header><div><div class="eyebrow">MAILVERSAND</div><h1>Mail verfassen</h1></div></header>
<div id="availability" class="notice" role="status" <?=!$capabilities['hinweise']?'hidden':''?>><?=h(implode("\n",$capabilities['hinweise']))?></div>
<?php if($capabilities['server'] && $c['MAIL_TRANSPORT']==='datei'):?><div class="notice">Testbetrieb: Der Server schreibt EML-Dateien. Es werden keine E-Mails zugestellt.</div><?php endif;?>
<noscript><p>Bitte JavaScript aktivieren, um Vorschau und Versand zu bedienen.</p></noscript>
<div id="notice" class="notice" role="status" hidden></div>
<div class="grid"><section class="card"><h2>Deine Nachricht</h2><p class="hint">Klartext mit einem Link. Empfänger bleiben bei den lokalen Wegen im BCC.</p>
<form id="compose"><label for="emails">Empfänger</label><textarea id="emails" name="emails" rows="3" placeholder="anna@beispiel.at; max@beispiel.at" required></textarea><p class="hint">Mit Semikolon, Komma oder Zeilenumbruch trennen. Dubletten und gesperrte Adressen werden entfernt.</p>
<label for="betreff">Betreff</label><input id="betreff" name="betreff" maxlength="255" required>
<label for="text">Nachricht</label><textarea id="text" name="text" rows="9" required>Guten Tag,

hier finden Sie die Informationen:
[[LINK]]

Beste Grüße</textarea><p class="hint">[[LINK]] wird durch den unten angegebenen Link ersetzt.</p>
<label for="url">Linkadresse</label><input id="url" name="url" type="url" placeholder="https://…" maxlength="1000" required>
<label for="label">Linkbeschriftung</label><input id="label" name="label" maxlength="160" value="Weitere Informationen" required>
<div <?=!$capabilities['server']?'hidden':''?>><label for="test_email">Adresse für die Testmail</label><input id="test_email" name="test_email" type="email" placeholder="test@beispiel.at"><p class="hint">Für den Testversand und den anschließenden Serverversand erforderlich.</p></div>
<div class="buttons"><button class="primary" type="submit">Vorschau erstellen</button></div></form>
</section>
<div><section class="card"><h2>Vorschau <span id="count" class="badge">Noch nicht erstellt</span></h2><p id="subject" class="hint">Prüfe Inhalt und Empfänger vor der Übergabe.</p><iframe id="preview" title="Vorschau der Nachricht" sandbox=""></iframe><p id="filtered" class="hint"></p></section>
<section class="card"><h2>Über mein Mailprogramm</h2><p class="hint">Entwurf herunterladen bzw. öffnen, Absender, Signatur und BCC prüfen und selbst senden. Die Anwendung kann den lokalen Versand nicht nachweisen.</p><div class="buttons"><button data-way="outlook_alt" disabled>Outlook klassisch</button><button data-way="outlook_neu" disabled>Outlook neu</button><button data-way="thunderbird" disabled>Thunderbird</button><button data-way="apple_mail" disabled>Apple Mail</button></div>
<div class="buttons"><button id="addresses" disabled>Adressliste kopieren</button></div>
<details <?=!$capabilities['server']?'hidden':''?>><summary>Optional: Direkt vom Server</summary><p class="hint">Absender: <strong><?=h($c['MAIL_FROM_ADDR'] ?: 'noch nicht konfiguriert')?></strong>. Jede Person erhält eine eigene Mail. Start nach <?=max(0,(int)$c['VERSAND_STORNO_MINUTEN'])?> Minuten; bis dahin abbrechbar.</p>
<div class="buttons"><button id="test" data-way="test" disabled>Testmail senden</button><button id="send" data-way="smtp" class="primary" disabled>Versand starten</button></div><p id="teststate" class="hint">Zuerst eine Vorschau erstellen. <?= $c['VERSAND_TEST_PFLICHT']==='true'?'Vor dem Serverweg muss der Worker den Test erfolgreich abarbeiten.':''?></p></details>
<div id="handoff" hidden><hr class="line"><h2>Im Mailprogramm weiterarbeiten</h2><div id="downloads" class="buttons"></div><p id="instructions" class="hint"></p><div id="blocks" class="buttons"></div><label for="fallback">Text zum manuellen Kopieren</label><textarea id="fallback" readonly></textarea><div id="addressCopy" hidden><label for="addressFallback">Empfängeradressen zum manuellen Kopieren</label><textarea id="addressFallback" readonly></textarea></div></div>
</section></div></div>
<section class="card"><details open><summary>Versanddokumentation – letzte 5 Einträge</summary><p class="hint">Dokumentiert wird die Bereitstellung eines Mailentwurfs mit Zeitpunkt und Empfängerzahl. Das Versanddatum ist der Übergabezeitpunkt, kein Versand- oder Zustellnachweis.</p><div class="buttons"><button id="refresh">Aktualisieren</button></div><div id="jobs" class="scroll"></div><div <?=!$capabilities['server']?'hidden':''?>><label for="searchEmail">Serverprotokoll für diese Adresse (diese Sitzung)</label><input id="searchEmail" type="email" placeholder="name@beispiel.at"><div class="buttons"><button id="searchLog">Protokoll durchsuchen</button></div></div><pre id="audit" hidden></pre></details></section>
</main><script nonce="<?=h($nonce)?>">
'use strict';
// UI-Zustand: Jede Bearbeitung entwertet Vorschau und Testfreigabe sofort.
const csrf=<?=json_encode($_SESSION['mail_csrf'])?>, testRequired=<?=json_encode($c['VERSAND_TEST_PFLICHT']==='true')?>;
const $=id=>document.getElementById(id), form=$('compose');
let capabilities=<?=json_encode($capabilities,JSON_HEX_TAG|JSON_HEX_AMP|JSON_HEX_APOS|JSON_HEX_QUOT)?>;
let prepared=null, testJob=null, testDone=false, busy=false, revision=0, requestKeys={};
const data=()=>Object.fromEntries(new FormData(form));
const key=()=>Array.from(crypto.getRandomValues(new Uint8Array(32)),x=>x.toString(16).padStart(2,'0')).join('');
function notice(text,error=false){$('notice').hidden=false;$('notice').textContent=text;$('notice').classList.toggle('error',error);}
async function api(action,extra={}){const r=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,csrf,...extra})});let j;try{j=await r.json();}catch{throw Error('Serverantwort unlesbar. Apache-Konfiguration prüfen.');}if(j.capabilities){const wasServer=capabilities.server;capabilities=j.capabilities;if(wasServer&&!capabilities.server){testDone=false;testJob=null;}$('availability').textContent=capabilities.hinweise.join('\n');$('availability').hidden=!capabilities.hinweise.length;controls();}if(!j.ok)throw Error(j.error||'Anfrage fehlgeschlagen.');return j;}
function controls(){document.querySelectorAll('[data-way]').forEach(b=>b.disabled=busy||!prepared||(['test','smtp'].includes(b.dataset.way)&&!capabilities.server)||(b.dataset.way==='smtp'&&testRequired&&!testDone));$('addresses').disabled=!prepared||busy;$('searchLog').disabled=!capabilities.server;}
form.addEventListener('input',()=>{revision++;prepared=null;testJob=null;testDone=false;requestKeys={};$('handoff').hidden=true;$('addressCopy').hidden=true;$('count').textContent='Vorschau veraltet';$('teststate').textContent='Inhalt geändert: Vorschau und Test erneut erstellen.';controls();});
form.addEventListener('submit',async e=>{e.preventDefault();const rev=revision;busy=true;controls();try{const m=await api('vorschau',data());if(rev!==revision)return;prepared=m;$('subject').textContent=m.subject;$('preview').srcdoc='<html lang="de"><meta charset="utf-8"><body>'+m.html+'</body></html>';$('count').textContent=m.emails.length+' Empfänger';$('filtered').textContent=m.duplicates+' Dubletten entfernt. '+(m.sperrliste_geprueft?m.blocked+' gesperrte Adressen entfernt.':'Keine Sperrlistenprüfung aktiviert oder verfügbar.');$('teststate').textContent='Vorschau bereit. Optional eine Testmail senden.';}catch(e){notice(e.message,true);}finally{busy=false;controls();}});
// Clipboard-Aufruf direkt im Klickereignis; Fallback bleibt immer sichtbar verfügbar.
async function copyText(text,target='fallback'){const field=$(target);$('handoff').hidden=false;if(target==='addressFallback')$('addressCopy').hidden=false;field.value=text;try{await navigator.clipboard.writeText(text);}catch{field.focus();field.select();notice('Zwischenablage nicht verfügbar. Markierten Text manuell kopieren.');}}
function emlHerunterladen(encoded,way,id){
 const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
 const url=URL.createObjectURL(new Blob([bytes],{type:'message/rfc822'}));
 const a=document.createElement('a');a.href=url;a.download='entwurf-'+way+'-'+(id??'lokal')+'.eml';
 document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
}
$('addresses').onclick=()=>{$('fallback').value=prepared.plain;return copyText(prepared.emails.join('; '),'addressFallback');};
document.querySelectorAll('[data-way]').forEach(button=>button.onclick=async()=>{
 if(!prepared||busy)return;const way=button.dataset.way,rev=revision;busy=true;controls();
 try{requestKeys[way]??=key();const j=await api(way,{...data(),request:requestKeys[way]});
   if(j.duplicate&&!j.eml&&!j.blocks){if(way==='test'&&rev===revision)testJob=j.id;notice('Dieser Auftrag wurde bereits angelegt: #'+j.id+'. Status unten prüfen.');await refresh();return;}
   notice(j.lokal?'Lokaler Entwurf bereit. Keine Protokollierung und keine Sperrlistenprüfung.':'Übergabe / Auftrag #'+j.id+' dokumentiert.');
   if(way==='test'){if(rev===revision){testJob=j.id;testDone=false;$('teststate').textContent='Test #'+j.id+' wartet auf den Worker.';}}
   else if(way==='smtp'){testDone=false;$('teststate').textContent='Auftrag angelegt. Fortschritt und Storno unten.';}
   else if(j.eml){
     $('handoff').hidden=false;$('blocks').replaceChildren();$('downloads').replaceChildren();
     const download=document.createElement('button');download.textContent='EML-Datei herunterladen';
     download.onclick=()=>emlHerunterladen(j.eml,way,j.id);$('downloads').append(download);
     emlHerunterladen(j.eml,way,j.id);
     $('fallback').value=j.plain;
     $('instructions').textContent=way==='outlook_neu'?'EML-Datei in Outlook neu öffnen und prüfen, ob sie als bearbeitbarer Entwurf erscheint.':way==='thunderbird'?'Datei in Thunderbird öffnen und „Als neu bearbeiten“. Bei Bedarf „Adressliste kopieren“ verwenden und die Adressen ins BCC einfügen.':way==='apple_mail'?'Datei in Apple Mail öffnen und „Erneut senden“. BCC prüfen.':'EML in Outlook klassisch öffnen. Absenderkonto, BCC und Signatur prüfen; anschließend selbst senden.';
     if(j.mailto_fehler) $('instructions').textContent='Die EML-Datei wurde zum Download bereitgestellt. Die Mailto-Alternative ist für diesen Entwurf nicht verfügbar: '+j.mailto_fehler;
   }
   if(j.blocks){$('handoff').hidden=false;$('fallback').value=j.plain;$('instructions').textContent+=' Alternativ per Mailto: Pro Block den Nachrichtentext kopieren und das Standard-Mailprogramm öffnen, dort mit Strg+V einfügen. Mailto startet das in deinem Betriebssystem eingestellte Standard-Mailprogramm, unabhängig vom hier ausgewählten Programm. Für denselben Versand entweder die EML-Datei oder die Mailto-Blöcke verwenden.';$('blocks').replaceChildren();j.blocks.forEach((block,i)=>{const b=document.createElement('button');b.textContent='Mailto öffnen · Block '+(i+1)+' · '+block.emails.length+' Empfänger';b.onclick=async()=>{try{if(!navigator.clipboard||!window.ClipboardItem)throw Error();await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([j.html],{type:'text/html'}),'text/plain':new Blob([j.plain],{type:'text/plain'})})]);}catch{await copyText(j.plain);}location.href=block.url;b.textContent='✓ Mailto für Block '+(i+1)+' aufgerufen';};$('blocks').append(b);});}
   await refresh();
 }catch(e){notice(e.message,true);}finally{busy=false;controls();}
});
// Statusanzeigen werden aus Serverzeit berechnet; der Server entscheidet über Storno.
async function refresh(){try{const j=await api('status');if(!capabilities.database){$('jobs').textContent='Versanddokumentation ist verfügbar, sobald die Dokumentationstabelle eingerichtet ist.';return;}const table=document.createElement('table');const head=document.createElement('tr');['Dokumentation','Status','Ergebnis','Aktionen'].forEach(t=>{const th=document.createElement('th');th.textContent=t;head.append(th);});table.append(head);
 for(const row of j.jobs){if(Number(row.id)===testJob&&(Number(row.gesendet)+Number(row.datei))===1){testDone=true;$('teststate').textContent=Number(row.datei)?'Dateitest erfolgreich; keine echte Zustellung.':'Test vom SMTP-Server angenommen. Bitte im Postfach prüfen.';controls();}
 const tr=document.createElement('tr');const cell=t=>{const td=document.createElement('td');td.textContent=t;tr.append(td);return td;};cell('#'+row.id+' · '+row.betreff+' ('+row.anzahl+')');cell(row.status+' · '+row.weg);cell(String(row.id).startsWith('d')?row.anzahl+' Empfänger · '+'Entwurf bereitgestellt · '+row.versanddatum+' UTC':row.gesendet+' SMTP / '+row.datei+' Datei / '+row.fehler+' Fehler oder unklar');const actions=cell('');
 const add=(title,action)=>{const b=document.createElement('button');b.textContent=title;if(action==='abbrechen')b.className='danger';b.onclick=async()=>{b.disabled=true;try{const result=await api(action,{id:row.id});if(action==='protokoll'){$('audit').hidden=false;$('audit').textContent=result.log.map(l=>l.zeit+' UTC | '+(l.empfaenger||'keine Einzeladresse')+' | '+l.ereignis+' '+(l.detail||'')).join('\n')||'Keine Einträge.';}else{notice('Auftrag #'+row.id+': '+title);await refresh();}}catch(e){notice(e.message,true);b.disabled=false;}};actions.append(b);return b;};
 if(row.benutzer===j.user){add('Protokoll','protokoll');if(row.status==='uebergeben')add('Selbst gesendet bestätigen','bestaetigen');const seconds=Math.floor((Date.parse(row.senden_ab+'Z')-Date.parse(row.jetzt+'Z'))/1000);if(row.status==='wartet_freigabe')add('Abbrechen','abbrechen');else if(row.status==='laeuft'&&row.weg==='smtp'&&seconds>0){const b=add('Versand abbrechen','abbrechen');b.dataset.deadline=String(Date.now()+seconds*1000);}}
 table.append(tr);
 }$('jobs').replaceChildren(table);
 }catch(e){notice(e.message,true);}}
$('searchLog').onclick=async()=>{try{const result=await api('suche',{email:$('searchEmail').value});$('audit').hidden=false;$('audit').textContent=result.log.map(l=>'#'+l.job_id+' | '+l.zeit+' UTC | '+l.empfaenger+' | '+l.ereignis+' '+(l.detail||'')).join('\n')||'Keine Einträge innerhalb der Aufbewahrungsfrist.';}catch(e){notice(e.message,true);}};
$('refresh').onclick=refresh;setInterval(refresh,10000);setInterval(()=>document.querySelectorAll('[data-deadline]').forEach(b=>{const s=Math.max(0,Math.ceil((Number(b.dataset.deadline)-Date.now())/1000));b.textContent='Abbrechen · '+Math.floor(s/60)+':'+String(s%60).padStart(2,'0');b.disabled=s===0;}),1000);refresh();
</script></body></html>
