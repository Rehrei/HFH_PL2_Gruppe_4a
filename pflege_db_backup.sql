-- MySQL dump 10.13  Distrib 8.0.46, for Win64 (x86_64)
--
-- Host: localhost    Database: pflege_db
-- ------------------------------------------------------
-- Server version	8.0.46

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `01_einrichtungstyp`
--

DROP TABLE IF EXISTS `01_einrichtungstyp`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `01_einrichtungstyp` (
  `einrichtungstyp_id` int NOT NULL AUTO_INCREMENT COMMENT 'Unique ID für den Einrichtungstyp',
  `einrichtungstyp` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Pflegeheim, Pflegedienst, Beratungsstelle, etc.',
  PRIMARY KEY (`einrichtungstyp_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `01_einrichtungstyp`
--

LOCK TABLES `01_einrichtungstyp` WRITE;
/*!40000 ALTER TABLE `01_einrichtungstyp` DISABLE KEYS */;
/*!40000 ALTER TABLE `01_einrichtungstyp` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `20_oeffnungszeiten`
--

DROP TABLE IF EXISTS `20_oeffnungszeiten`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `20_oeffnungszeiten` (
  `oeffnungszeit_id` int NOT NULL AUTO_INCREMENT,
  `pflegeeinrichtung_id` int DEFAULT NULL,
  `wochentag` tinyint NOT NULL,
  `oeffnet` time NOT NULL,
  `schliesst` time NOT NULL,
  PRIMARY KEY (`oeffnungszeit_id`),
  UNIQUE KEY `pflegeeinrichtung_id_UNIQUE` (`pflegeeinrichtung_id`),
  KEY `pflegeeinrichtung_id_idx` (`pflegeeinrichtung_id`),
  CONSTRAINT `pflegeeinrichtung_id` FOREIGN KEY (`pflegeeinrichtung_id`) REFERENCES `22_pflegeeinrichtung` (`pflegeeinrichtung_id`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `20_oeffnungszeiten`
--

LOCK TABLES `20_oeffnungszeiten` WRITE;
/*!40000 ALTER TABLE `20_oeffnungszeiten` DISABLE KEYS */;
/*!40000 ALTER TABLE `20_oeffnungszeiten` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `21_ansprechpartner`
--

DROP TABLE IF EXISTS `21_ansprechpartner`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `21_ansprechpartner` (
  `ansprechpartner_id` int NOT NULL AUTO_INCREMENT,
  `pflegeeinrichtung_id` int NOT NULL COMMENT 'könnte man evtl noch unique setzen',
  `vorname` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `nachname` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `telefon` varchar(45) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `e-mail` varchar(254) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `funktion` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`ansprechpartner_id`),
  KEY `pflegeeinrichtung_id_idx` (`pflegeeinrichtung_id`),
  CONSTRAINT `pflegeeinrichtung_id2` FOREIGN KEY (`pflegeeinrichtung_id`) REFERENCES `22_pflegeeinrichtung` (`pflegeeinrichtung_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `21_ansprechpartner`
--

LOCK TABLES `21_ansprechpartner` WRITE;
/*!40000 ALTER TABLE `21_ansprechpartner` DISABLE KEYS */;
/*!40000 ALTER TABLE `21_ansprechpartner` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `22_pflegeeinrichtung`
--

DROP TABLE IF EXISTS `22_pflegeeinrichtung`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `22_pflegeeinrichtung` (
  `pflegeeinrichtung_id` int NOT NULL AUTO_INCREMENT,
  `einrichtungstyp_id` int NOT NULL,
  `einrichtungsname` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `webseite` varchar(2048) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `strasse` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hausnummer` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `plz` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ort` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `gemeinde_stadt` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `landkreis` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `bundesland` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `breitengrad` decimal(9,6) DEFAULT NULL,
  `laengengrad` decimal(9,6) DEFAULT NULL,
  PRIMARY KEY (`pflegeeinrichtung_id`),
  KEY `einrichtungstyp_id_idx` (`einrichtungstyp_id`),
  CONSTRAINT `einrichtungstyp_id` FOREIGN KEY (`einrichtungstyp_id`) REFERENCES `01_einrichtungstyp` (`einrichtungstyp_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `22_pflegeeinrichtung`
--

LOCK TABLES `22_pflegeeinrichtung` WRITE;
/*!40000 ALTER TABLE `22_pflegeeinrichtung` DISABLE KEYS */;
/*!40000 ALTER TABLE `22_pflegeeinrichtung` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `30_benutzerrolle`
--

DROP TABLE IF EXISTS `30_benutzerrolle`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `30_benutzerrolle` (
  `rolle_id` int NOT NULL AUTO_INCREMENT,
  `rollenname` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Administrator, Sachbearbeiter, Leser',
  `beschreibung` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`rolle_id`),
  UNIQUE KEY `rollenname_UNIQUE` (`rollenname`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `30_benutzerrolle`
--

LOCK TABLES `30_benutzerrolle` WRITE;
/*!40000 ALTER TABLE `30_benutzerrolle` DISABLE KEYS */;
/*!40000 ALTER TABLE `30_benutzerrolle` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `31_benutzer`
--

DROP TABLE IF EXISTS `31_benutzer`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `31_benutzer` (
  `benutzer_id` int NOT NULL,
  `rolle_id` int NOT NULL,
  `benutzername` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `passwort` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `vorname` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `nachname` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `e-mail` varchar(254) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` enum('aktiv','deaktiviert') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'aktiv',
  `api_key_hash` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`benutzer_id`),
  UNIQUE KEY `benutzername_UNIQUE` (`benutzername`),
  UNIQUE KEY `e-mail_UNIQUE` (`e-mail`),
  KEY `rolle_id_idx` (`rolle_id`),
  CONSTRAINT `rolle_id` FOREIGN KEY (`rolle_id`) REFERENCES `30_benutzerrolle` (`rolle_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `31_benutzer`
--

LOCK TABLES `31_benutzer` WRITE;
/*!40000 ALTER TABLE `31_benutzer` DISABLE KEYS */;
/*!40000 ALTER TABLE `31_benutzer` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `32_einzelrechte`
--

DROP TABLE IF EXISTS `32_einzelrechte`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `32_einzelrechte` (
  `recht_id` int NOT NULL AUTO_INCREMENT,
  `rechte_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `beschreibung` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`recht_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `32_einzelrechte`
--

LOCK TABLES `32_einzelrechte` WRITE;
/*!40000 ALTER TABLE `32_einzelrechte` DISABLE KEYS */;
/*!40000 ALTER TABLE `32_einzelrechte` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `33_rollenrechte`
--

DROP TABLE IF EXISTS `33_rollenrechte`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `33_rollenrechte` (
  `rolle_id` int NOT NULL,
  `recht_id` int NOT NULL,
  PRIMARY KEY (`rolle_id`,`recht_id`),
  KEY `recht_idx` (`recht_id`),
  CONSTRAINT `recht` FOREIGN KEY (`recht_id`) REFERENCES `32_einzelrechte` (`recht_id`),
  CONSTRAINT `rolle` FOREIGN KEY (`rolle_id`) REFERENCES `30_benutzerrolle` (`rolle_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `33_rollenrechte`
--

LOCK TABLES `33_rollenrechte` WRITE;
/*!40000 ALTER TABLE `33_rollenrechte` DISABLE KEYS */;
/*!40000 ALTER TABLE `33_rollenrechte` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `40_maildokumentation`
--

DROP TABLE IF EXISTS `40_maildokumentation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `40_maildokumentation` (
  `mail_id` int NOT NULL AUTO_INCREMENT,
  `benutzer_id` int NOT NULL,
  `betreff` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `nachricht` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `versanddatum` datetime NOT NULL,
  `empfaengerzahl` int NOT NULL,
  PRIMARY KEY (`mail_id`),
  KEY `benutzer_id_mail_idx` (`benutzer_id`),
  CONSTRAINT `benutzer_id_mail` FOREIGN KEY (`benutzer_id`) REFERENCES `31_benutzer` (`benutzer_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `40_maildokumentation`
--

LOCK TABLES `40_maildokumentation` WRITE;
/*!40000 ALTER TABLE `40_maildokumentation` DISABLE KEYS */;
/*!40000 ALTER TABLE `40_maildokumentation` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-11-06 17:23:35
