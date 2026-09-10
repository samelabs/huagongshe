--
-- PostgreSQL database dump
--

\restrict heaavEZI2Lyll5yaWSbJdyvZTzcRir5zeofKT9HYo6Koeqwwp3mkU9JR1kjKHSL

-- Dumped from database version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: chemistry; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA chemistry;


--
-- Name: SCHEMA chemistry; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA chemistry IS '化工社自主维护的化合物与反应核心数据';


--
-- Name: community; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA community;


--
-- Name: SCHEMA community; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA community IS '用户、会话、提交与反应求助工作流';


--
-- Name: ingest; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ingest;


--
-- Name: SCHEMA ingest; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA ingest IS '一次性导入、迁移和质量审计数据，不供线上业务直接查询';


--
-- Name: ingestion; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ingestion;


--
-- Name: maintenance; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA maintenance;


--
-- Name: ord; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ord;


--
-- Name: SCHEMA ord; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA ord IS 'ORD 原始反应事实和来源上下文';


--
-- Name: rdkit; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA rdkit;


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: rdkit; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS rdkit WITH SCHEMA public;


--
-- Name: EXTENSION rdkit; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION rdkit IS 'Cheminformatics functionality for PostgreSQL.';


--
-- Name: tsm_system_rows; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS tsm_system_rows WITH SCHEMA public;


--
-- Name: EXTENSION tsm_system_rows; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION tsm_system_rows IS 'TABLESAMPLE method which accepts number of rows as a limit';


--
-- Name: AdditionDeviceType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."AdditionDeviceType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'NONE',
    'SYRINGE',
    'CANNULA',
    'ADDITION_FUNNEL',
    'PIPETTE',
    'POSITIVE_DISPLACEMENT_PIPETTE',
    'PISTON_PUMP',
    'SYRINGE_PUMP',
    'PERISTALTIC_PUMP'
);


--
-- Name: AdditionSpeedType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."AdditionSpeedType" AS ENUM (
    'UNSPECIFIED',
    'ALL_AT_ONCE',
    'FAST',
    'SLOW',
    'DROPWISE',
    'CONTINUOUS',
    'PORTIONWISE'
);


--
-- Name: AnalysisType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."AnalysisType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'LC',
    'GC',
    'IR',
    'NMR_1H',
    'NMR_13C',
    'NMR_OTHER',
    'MP',
    'UV',
    'TLC',
    'MS',
    'HRMS',
    'MSMS',
    'WEIGHT',
    'LCMS',
    'GCMS',
    'ELSD',
    'CD',
    'SFC',
    'EPR',
    'XRD',
    'RAMAN',
    'ED',
    'OPTICAL_ROTATION',
    'CAD'
);


--
-- Name: AtmosphereType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."AtmosphereType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'AIR',
    'NITROGEN',
    'ARGON',
    'OXYGEN',
    'HYDROGEN',
    'CARBON_MONOXIDE',
    'CARBON_DIOXIDE',
    'METHANE',
    'AMMONIA',
    'OZONE',
    'ETHYLENE',
    'ACETYLENE'
);


--
-- Name: CompoundIdentifierType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."CompoundIdentifierType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'SMILES',
    'INCHI',
    'MOLBLOCK',
    'IUPAC_NAME',
    'NAME',
    'CAS_NUMBER',
    'PUBCHEM_CID',
    'CHEMSPIDER_ID',
    'CXSMILES',
    'INCHI_KEY',
    'XYZ',
    'UNIPROT_ID',
    'PDB_ID',
    'AMINO_ACID_SEQUENCE',
    'HELM',
    'MDL'
);


--
-- Name: CompoundPreparationType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."CompoundPreparationType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'NONE',
    'REPURIFIED',
    'SPARGED',
    'DRIED',
    'SYNTHESIZED'
);


--
-- Name: CurrentUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."CurrentUnit" AS ENUM (
    'UNSPECIFIED',
    'AMPERE',
    'MILLIAMPERE'
);


--
-- Name: ElectrochemistryCellType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ElectrochemistryCellType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'DIVIDED_CELL',
    'UNDIVIDED_CELL'
);


--
-- Name: ElectrochemistryType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ElectrochemistryType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'CONSTANT_CURRENT',
    'CONSTANT_VOLTAGE'
);


--
-- Name: FlowRateUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."FlowRateUnit" AS ENUM (
    'UNSPECIFIED',
    'MICROLITER_PER_MINUTE',
    'MICROLITER_PER_SECOND',
    'MILLILITER_PER_MINUTE',
    'MILLILITER_PER_SECOND',
    'MICROLITER_PER_HOUR'
);


--
-- Name: FlowType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."FlowType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'PLUG_FLOW_REACTOR',
    'CONTINUOUS_STIRRED_TANK_REACTOR',
    'PACKED_BED_REACTOR'
);


--
-- Name: IlluminationType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."IlluminationType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'AMBIENT',
    'DARK',
    'LED',
    'HALOGEN_LAMP',
    'DEUTERIUM_LAMP',
    'SOLAR_SIMULATOR',
    'BROAD_SPECTRUM'
);


--
-- Name: LengthUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."LengthUnit" AS ENUM (
    'UNSPECIFIED',
    'CENTIMETER',
    'MILLIMETER',
    'METER',
    'INCH',
    'FOOT'
);


--
-- Name: MassSpecMeasurementType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."MassSpecMeasurementType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'TIC',
    'TIC_POSITIVE',
    'TIC_NEGATIVE',
    'EIC'
);


--
-- Name: MassUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."MassUnit" AS ENUM (
    'UNSPECIFIED',
    'KILOGRAM',
    'GRAM',
    'MILLIGRAM',
    'MICROGRAM'
);


--
-- Name: MolesUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."MolesUnit" AS ENUM (
    'UNSPECIFIED',
    'MOLE',
    'MILLIMOLE',
    'MICROMOLE',
    'NANOMOLE'
);


--
-- Name: PressureControlType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."PressureControlType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'AMBIENT',
    'SLIGHT_POSITIVE',
    'SEALED',
    'PRESSURIZED'
);


--
-- Name: PressureMeasurementType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."PressureMeasurementType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'PRESSURE_TRANSDUCER'
);


--
-- Name: PressureUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."PressureUnit" AS ENUM (
    'UNSPECIFIED',
    'BAR',
    'ATMOSPHERE',
    'PSI',
    'KPSI',
    'PASCAL',
    'KILOPASCAL',
    'TORR',
    'MM_HG'
);


--
-- Name: ProductMeasurementType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ProductMeasurementType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'IDENTITY',
    'YIELD',
    'SELECTIVITY',
    'PURITY',
    'AREA',
    'COUNTS',
    'INTENSITY',
    'AMOUNT'
);


--
-- Name: ReactionEnvironmentType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ReactionEnvironmentType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'FUME_HOOD',
    'BENCH_TOP',
    'GLOVE_BOX',
    'GLOVE_BAG'
);


--
-- Name: ReactionIdentifierType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ReactionIdentifierType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'REACTION_SMILES',
    'REACTION_CXSMILES',
    'RDFILE',
    'RINCHI',
    'REACTION_TYPE'
);


--
-- Name: ReactionRoleType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ReactionRoleType" AS ENUM (
    'UNSPECIFIED',
    'REACTANT',
    'REAGENT',
    'SOLVENT',
    'CATALYST',
    'WORKUP',
    'INTERNAL_STANDARD',
    'AUTHENTIC_STANDARD',
    'PRODUCT',
    'BYPRODUCT',
    'SIDE_PRODUCT'
);


--
-- Name: ReactionWorkupType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ReactionWorkupType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'ADDITION',
    'ALIQUOT',
    'TEMPERATURE',
    'CONCENTRATION',
    'EXTRACTION',
    'FILTRATION',
    'WASH',
    'DRY_IN_VACUUM',
    'DRY_WITH_MATERIAL',
    'FLASH_CHROMATOGRAPHY',
    'OTHER_CHROMATOGRAPHY',
    'SCAVENGING',
    'WAIT',
    'STIRRING',
    'PH_ADJUST',
    'DISSOLUTION',
    'DISTILLATION'
);


--
-- Name: SelectivityType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."SelectivityType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'EE',
    'ER',
    'DR',
    'EZ',
    'ZE'
);


--
-- Name: StirringMethodType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."StirringMethodType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'NONE',
    'STIR_BAR',
    'OVERHEAD_MIXER',
    'AGITATION',
    'BALL_MILLING',
    'SONICATION'
);


--
-- Name: StirringRateType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."StirringRateType" AS ENUM (
    'UNSPECIFIED',
    'HIGH',
    'MEDIUM',
    'LOW'
);


--
-- Name: TemperatureControlType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."TemperatureControlType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'AMBIENT',
    'OIL_BATH',
    'WATER_BATH',
    'SAND_BATH',
    'ICE_BATH',
    'DRY_ALUMINUM_PLATE',
    'MICROWAVE',
    'DRY_ICE_BATH',
    'AIR_FAN',
    'LIQUID_NITROGEN'
);


--
-- Name: TemperatureMeasurementType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."TemperatureMeasurementType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'THERMOCOUPLE_INTERNAL',
    'THERMOCOUPLE_EXTERNAL',
    'INFRARED'
);


--
-- Name: TemperatureUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."TemperatureUnit" AS ENUM (
    'UNSPECIFIED',
    'CELSIUS',
    'FAHRENHEIT',
    'KELVIN'
);


--
-- Name: TextureType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."TextureType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'POWDER',
    'CRYSTAL',
    'OIL',
    'AMORPHOUS_SOLID',
    'FOAM',
    'WAX',
    'SEMI_SOLID',
    'SOLID',
    'LIQUID',
    'GAS'
);


--
-- Name: TimeUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."TimeUnit" AS ENUM (
    'UNSPECIFIED',
    'DAY',
    'HOUR',
    'MINUTE',
    'SECOND'
);


--
-- Name: TubingType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."TubingType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'STEEL',
    'COPPER',
    'PFA',
    'FEP',
    'TEFLONAF',
    'PTFE',
    'GLASS',
    'QUARTZ',
    'SILICON',
    'PDMS'
);


--
-- Name: UnmeasuredAmountType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."UnmeasuredAmountType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'SATURATED',
    'CATALYTIC',
    'TITRATED'
);


--
-- Name: VesselAttachmentType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."VesselAttachmentType" AS ENUM (
    'UNSPECIFIED',
    'NONE',
    'CUSTOM',
    'SEPTUM',
    'CAP',
    'MAT',
    'REFLUX_CONDENSER',
    'VENT_NEEDLE',
    'DEAN_STARK',
    'VACUUM_TUBE',
    'ADDITION_FUNNEL',
    'DRYING_TUBE',
    'ALUMINUM_FOIL',
    'THERMOCOUPLE',
    'BALLOON',
    'GAS_ADAPTER',
    'PRESSURE_REGULATOR',
    'RELEASE_VALVE'
);


--
-- Name: VesselMaterialType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."VesselMaterialType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'GLASS',
    'POLYPROPYLENE',
    'PLASTIC',
    'METAL',
    'QUARTZ'
);


--
-- Name: VesselPreparationType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."VesselPreparationType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'NONE',
    'OVEN_DRIED',
    'FLAME_DRIED',
    'EVACUATED_BACKFILLED',
    'PURGED'
);


--
-- Name: VesselType; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."VesselType" AS ENUM (
    'UNSPECIFIED',
    'CUSTOM',
    'ROUND_BOTTOM_FLASK',
    'VIAL',
    'WELL_PLATE',
    'MICROWAVE_VIAL',
    'TUBE',
    'CONTINUOUS_STIRRED_TANK_REACTOR',
    'PACKED_BED_REACTOR',
    'NMR_TUBE',
    'PRESSURE_FLASK',
    'PRESSURE_REACTOR',
    'ELECTROCHEMICAL_CELL'
);


--
-- Name: VoltageUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."VoltageUnit" AS ENUM (
    'UNSPECIFIED',
    'VOLT',
    'MILLIVOLT'
);


--
-- Name: VolumeUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."VolumeUnit" AS ENUM (
    'UNSPECIFIED',
    'LITER',
    'MILLILITER',
    'MICROLITER',
    'NANOLITER'
);


--
-- Name: WavelengthUnit; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."WavelengthUnit" AS ENUM (
    'UNSPECIFIED',
    'NANOMETER',
    'WAVENUMBER'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: chemical_cb; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.chemical_cb (
    chemical_id integer NOT NULL,
    cas_number text NOT NULL,
    entry jsonb,
    last_status text DEFAULT 'ok'::text NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    locale text DEFAULT 'zh-CN'::text NOT NULL,
    id bigint NOT NULL,
    cb_number text,
    CONSTRAINT cas_externals_last_status_check CHECK ((last_status = ANY (ARRAY['ok'::text, 'not_found'::text, 'error'::text]))),
    CONSTRAINT chemical_cb_locale_check CHECK ((locale = ANY (ARRAY['zh-CN'::text, 'en'::text, 'ja'::text, 'de'::text, 'ko'::text])))
);


--
-- Name: chemical_cb_id_seq; Type: SEQUENCE; Schema: chemistry; Owner: -
--

ALTER TABLE chemistry.chemical_cb ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME chemistry.chemical_cb_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: chemical_cb_premigrate_0905_bak; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.chemical_cb_premigrate_0905_bak (
    chemical_id integer,
    cas_number text,
    entry jsonb,
    last_status text,
    fetched_at timestamp with time zone,
    expires_at timestamp with time zone,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    locale text
);


--
-- Name: chemical_pubchem; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.chemical_pubchem (
    chemical_id integer NOT NULL,
    record_title text,
    record_description text,
    xlogp double precision,
    topological_polar_surface_area double precision,
    complexity double precision,
    hbond_donor_count integer,
    hbond_acceptor_count integer,
    rotatable_bond_count integer,
    heavy_atom_count integer,
    formal_charge integer,
    computed_properties jsonb DEFAULT '{}'::jsonb NOT NULL,
    physical_properties jsonb DEFAULT '{}'::jsonb NOT NULL,
    ghs_classification jsonb DEFAULT '{}'::jsonb NOT NULL,
    hazards jsonb DEFAULT '{}'::jsonb NOT NULL,
    safety_measures jsonb DEFAULT '{}'::jsonb NOT NULL,
    toxicity jsonb DEFAULT '{}'::jsonb NOT NULL,
    regulatory jsonb DEFAULT '{}'::jsonb NOT NULL,
    pharmacology jsonb DEFAULT '{}'::jsonb NOT NULL,
    uses_and_manufacturing jsonb DEFAULT '{}'::jsonb NOT NULL,
    identifier_evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_references jsonb DEFAULT '{}'::jsonb NOT NULL,
    pubchem_created_on date,
    pubchem_modified_on date,
    fetched_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    external_ids jsonb DEFAULT '{}'::jsonb NOT NULL,
    ghs_codes jsonb DEFAULT '{}'::jsonb NOT NULL,
    reactivity jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT chemical_details_nonnegative_counts CHECK ((((hbond_donor_count IS NULL) OR (hbond_donor_count >= 0)) AND ((hbond_acceptor_count IS NULL) OR (hbond_acceptor_count >= 0)) AND ((rotatable_bond_count IS NULL) OR (rotatable_bond_count >= 0)) AND ((heavy_atom_count IS NULL) OR (heavy_atom_count >= 0))))
);


--
-- Name: chemical_pubchem_expprops_clean2_0905_bak; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.chemical_pubchem_expprops_clean2_0905_bak (
    chemical_id integer,
    exp_props jsonb
);


--
-- Name: chemical_pubchem_expprops_clean_0905_bak; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.chemical_pubchem_expprops_clean_0905_bak (
    chemical_id integer,
    k text,
    entry jsonb
);


--
-- Name: chemical_pubchem_physical_0905_bak; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.chemical_pubchem_physical_0905_bak (
    chemical_id integer,
    physical_properties jsonb
);


--
-- Name: chemical_supplier_listing; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.chemical_supplier_listing (
    chemical_id integer NOT NULL,
    cbsid text NOT NULL,
    purity text,
    pack_price text,
    remark text,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: chemical_supplier_profile; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.chemical_supplier_profile (
    cbsid text NOT NULL,
    name text NOT NULL,
    ref text,
    phone text,
    email text,
    website text,
    locale text,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone DEFAULT (now() + '180 days'::interval) NOT NULL
);


--
-- Name: chemicals; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.chemicals (
    id integer NOT NULL,
    pubchem_cid integer,
    pubchem_smiles text,
    smiles text,
    preferred_name text,
    synonyms jsonb,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    cas_numbers text[],
    nikkaji_numbers text[],
    chembl_ids text[],
    ec_numbers text[],
    unii_codes text[],
    chebi_ids text[],
    dtxsid text,
    iupac_name text,
    molecular_formula text,
    average_mass double precision,
    monoisotopic_mass double precision,
    inchikey text,
    mol public.mol,
    morgan_bfp public.bfp,
    morgan_sfp public.sfp,
    cb_number text
)
WITH (fillfactor='100');
ALTER TABLE ONLY chemistry.chemicals ALTER COLUMN cas_numbers SET STATISTICS 500;
ALTER TABLE ONLY chemistry.chemicals ALTER COLUMN nikkaji_numbers SET STATISTICS 500;
ALTER TABLE ONLY chemistry.chemicals ALTER COLUMN chembl_ids SET STATISTICS 500;
ALTER TABLE ONLY chemistry.chemicals ALTER COLUMN ec_numbers SET STATISTICS 500;
ALTER TABLE ONLY chemistry.chemicals ALTER COLUMN unii_codes SET STATISTICS 500;
ALTER TABLE ONLY chemistry.chemicals ALTER COLUMN chebi_ids SET STATISTICS 500;


--
-- Name: COLUMN chemicals.id; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.id IS 'Autonomous chemical identity; independent of source namespaces';


--
-- Name: COLUMN chemicals.pubchem_cid; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.pubchem_cid IS 'Nullable PubChem source identifier; no longer the primary key';


--
-- Name: COLUMN chemicals.pubchem_smiles; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.pubchem_smiles IS 'Raw PubChem source SMILES; nullable for non-PubChem chemicals';


--
-- Name: COLUMN chemicals.smiles; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.smiles IS 'Canonical RDKit structure expression owned by chemicals';


--
-- Name: COLUMN chemicals.preferred_name; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.preferred_name IS 'Curated preferred display name; DSSTox is the initial source';


--
-- Name: COLUMN chemicals.dtxsid; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.dtxsid IS 'EPA DSSTox substance identifier; scalar source identity';


--
-- Name: COLUMN chemicals.iupac_name; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.iupac_name IS 'Curated systematic name; DSSTox is the initial source';


--
-- Name: COLUMN chemicals.molecular_formula; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.molecular_formula IS 'Materialized from canonical chemicals SMILES by RDKit';


--
-- Name: COLUMN chemicals.average_mass; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.average_mass IS 'Average molecular mass materialized from canonical chemicals SMILES by RDKit';


--
-- Name: COLUMN chemicals.monoisotopic_mass; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.monoisotopic_mass IS 'Monoisotopic exact mass materialized from canonical chemicals SMILES by RDKit';


--
-- Name: COLUMN chemicals.inchikey; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.inchikey IS 'Standard InChIKey materialized from canonical chemicals SMILES by RDKit';


--
-- Name: COLUMN chemicals.mol; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.mol IS 'Derived RDKit Cartridge Mol; rebuildable from chemicals.smiles';


--
-- Name: COLUMN chemicals.morgan_bfp; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.morgan_bfp IS 'Derived Morgan bit fingerprint for similarity search';


--
-- Name: COLUMN chemicals.morgan_sfp; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON COLUMN chemistry.chemicals.morgan_sfp IS 'Derived Morgan sparse fingerprint for similarity search';


--
-- Name: chemicals_id_seq; Type: SEQUENCE; Schema: chemistry; Owner: -
--

CREATE SEQUENCE chemistry.chemicals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chemicals_id_seq; Type: SEQUENCE OWNED BY; Schema: chemistry; Owner: -
--

ALTER SEQUENCE chemistry.chemicals_id_seq OWNED BY chemistry.chemicals.id;


--
-- Name: name_index; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.name_index (
    chemical_id integer NOT NULL,
    name text NOT NULL,
    lang text NOT NULL,
    normalized text NOT NULL,
    source text NOT NULL,
    kind text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT name_index_kind_check CHECK ((kind = ANY (ARRAY['name_cn'::text, 'name_en'::text, 'alias_cn'::text, 'alias_en'::text, 'supplier'::text, 'synonym_en'::text]))),
    CONSTRAINT name_index_lang_check CHECK ((lang = ANY (ARRAY['cn'::text, 'en'::text]))),
    CONSTRAINT name_index_source_check CHECK ((source = ANY (ARRAY['cb'::text, 'pubchem'::text])))
);


--
-- Name: TABLE name_index; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON TABLE chemistry.name_index IS '名称检索字典: CB 中文名/别名/供应商名 + PubChem synonyms 的派生镜像, 由摄入函数全量替换维护';


--
-- Name: reaction_chemicals; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.reaction_chemicals (
    reaction_id bigint NOT NULL,
    chemical_id integer NOT NULL,
    role text NOT NULL,
    occurrence_count integer NOT NULL,
    amount_value double precision,
    amount_unit text,
    equivalents double precision,
    concentration_value double precision,
    concentration_unit text,
    yield_percent double precision,
    CONSTRAINT reaction_chemicals_amount_check CHECK (((amount_value IS NULL) OR (amount_value >= (0)::double precision))),
    CONSTRAINT reaction_chemicals_concentration_check CHECK (((concentration_value IS NULL) OR (concentration_value >= (0)::double precision))),
    CONSTRAINT reaction_chemicals_equivalents_check CHECK (((equivalents IS NULL) OR (equivalents >= (0)::double precision))),
    CONSTRAINT reaction_chemicals_occurrence_count_check CHECK ((occurrence_count > 0)),
    CONSTRAINT reaction_chemicals_yield_check CHECK (((yield_percent IS NULL) OR ((yield_percent >= (0)::double precision) AND (yield_percent <= (100)::double precision))))
);


--
-- Name: reactions; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.reactions (
    id bigint NOT NULL,
    reaction_smiles text,
    reaction public.reaction,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by_user_id bigint,
    visibility text DEFAULT 'public'::text NOT NULL,
    moderation_status text DEFAULT 'visible'::text NOT NULL,
    created_via text DEFAULT 'import'::text NOT NULL,
    procedure_details text,
    conditions_detail text,
    temperature_value double precision,
    temperature_unit text,
    duration_value double precision,
    duration_unit text,
    ph double precision,
    atmosphere text,
    pressure_value double precision,
    pressure_unit text,
    workup_details text,
    safety_notes text,
    source_type text,
    doi text,
    patent text,
    source_url text,
    source_citation text,
    note text,
    idempotency_key text,
    CONSTRAINT reactions_created_via_check CHECK ((created_via = ANY (ARRAY['import'::text, 'web'::text, 'agent'::text]))),
    CONSTRAINT reactions_duration_unit_check CHECK (((duration_unit IS NULL) OR (duration_unit = ANY (ARRAY['MINUTE'::text, 'HOUR'::text, 'DAY'::text])))),
    CONSTRAINT reactions_moderation_status_check CHECK ((moderation_status = ANY (ARRAY['visible'::text, 'hidden'::text]))),
    CONSTRAINT reactions_ph_check CHECK (((ph IS NULL) OR ((ph >= (0)::double precision) AND (ph <= (14)::double precision)))),
    CONSTRAINT reactions_source_type_check CHECK (((source_type IS NULL) OR (source_type = ANY (ARRAY['self'::text, 'doi'::text, 'patent'::text, 'database'::text, 'url'::text, 'other'::text])))),
    CONSTRAINT reactions_temperature_unit_check CHECK (((temperature_unit IS NULL) OR (temperature_unit = ANY (ARRAY['CELSIUS'::text, 'KELVIN'::text])))),
    CONSTRAINT reactions_user_source_check CHECK (((created_by_user_id IS NULL) OR (source_type IS NOT NULL))),
    CONSTRAINT reactions_visibility_check CHECK ((visibility = ANY (ARRAY['public'::text, 'private'::text])))
);


--
-- Name: reactions_id_seq; Type: SEQUENCE; Schema: chemistry; Owner: -
--

ALTER TABLE chemistry.reactions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME chemistry.reactions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: statistics; Type: TABLE; Schema: chemistry; Owner: -
--

CREATE TABLE chemistry.statistics (
    metric text NOT NULL,
    exact_count bigint NOT NULL,
    calculated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT statistics_exact_count_check CHECK ((exact_count >= 0))
);


--
-- Name: TABLE statistics; Type: COMMENT; Schema: chemistry; Owner: -
--

COMMENT ON TABLE chemistry.statistics IS '首页和 API 使用的核心实体准确计数，避免在线扫描大型事实表';


--
-- Name: chemical_follows; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.chemical_follows (
    user_id bigint NOT NULL,
    chemical_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: notifications; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.notifications (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    event_type text NOT NULL,
    actor_user_id bigint,
    reaction_id bigint,
    chemical_id integer,
    dedupe_key text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    read_at timestamp with time zone,
    CONSTRAINT notifications_event_type_check CHECK ((event_type = 'new_reaction'::text))
);


--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: community; Owner: -
--

ALTER TABLE community.notifications ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME community.notifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: reaction_follows; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.reaction_follows (
    user_id bigint NOT NULL,
    reaction_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sessions; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.sessions (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    token_hash bytea NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sessions_id_seq; Type: SEQUENCE; Schema: community; Owner: -
--

ALTER TABLE community.sessions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME community.sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: skill_categories; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.skill_categories (
    id bigint NOT NULL,
    name text NOT NULL,
    abbr text NOT NULL,
    color text NOT NULL,
    sort_order integer DEFAULT 100 NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT skill_categories_abbr_check CHECK ((abbr ~ '^[A-Z]{1,4}$'::text)),
    CONSTRAINT skill_categories_color_check CHECK ((color ~ '^#[0-9a-f]{6}$'::text)),
    CONSTRAINT skill_categories_name_check CHECK (((char_length(name) >= 1) AND (char_length(name) <= 40)))
);


--
-- Name: skill_categories_id_seq; Type: SEQUENCE; Schema: community; Owner: -
--

ALTER TABLE community.skill_categories ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME community.skill_categories_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: skill_files; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.skill_files (
    id bigint NOT NULL,
    skill_id bigint NOT NULL,
    path text NOT NULL,
    is_text boolean NOT NULL,
    size_bytes integer NOT NULL,
    sha256 text NOT NULL,
    is_entry boolean DEFAULT false NOT NULL,
    CONSTRAINT skill_files_path_check CHECK (((path ~ '^([a-zA-Z0-9._-]+(/[a-zA-Z0-9._-]+)*)?$'::text) AND (path !~~ '%..%'::text))),
    CONSTRAINT skill_files_size_range CHECK (((size_bytes >= 0) AND (size_bytes <= 2097152))),
    CONSTRAINT skill_files_text_only CHECK ((is_text OR (path ~~ 'assets/%'::text) OR (path ~~ 'examples/%'::text)))
);


--
-- Name: skill_files_id_seq; Type: SEQUENCE; Schema: community; Owner: -
--

ALTER TABLE community.skill_files ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME community.skill_files_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: skills; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.skills (
    id bigint NOT NULL,
    owner_id bigint NOT NULL,
    slug text NOT NULL,
    title text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    license text DEFAULT 'MIT'::text NOT NULL,
    category text,
    origin text DEFAULT 'user'::text NOT NULL,
    visibility text DEFAULT 'private'::text NOT NULL,
    has_scripts boolean DEFAULT false NOT NULL,
    file_count integer DEFAULT 0 NOT NULL,
    size_bytes bigint DEFAULT 0 NOT NULL,
    idempotency_key text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    published_by bigint,
    published_at timestamp with time zone,
    publish_note text,
    CONSTRAINT skills_description_length CHECK ((char_length(description) <= 500)),
    CONSTRAINT skills_file_count_range CHECK (((file_count >= 0) AND (file_count <= 128))),
    CONSTRAINT skills_origin_check CHECK ((origin = ANY (ARRAY['user'::text, 'official'::text, 'kdense'::text]))),
    CONSTRAINT skills_publish_note_check CHECK ((char_length(publish_note) <= 200)),
    CONSTRAINT skills_size_range CHECK (((size_bytes >= 0) AND (size_bytes <= 10485760))),
    CONSTRAINT skills_slug_check CHECK ((slug ~ '^[a-z0-9][a-z0-9-]{0,63}$'::text)),
    CONSTRAINT skills_title_length CHECK (((char_length(title) >= 1) AND (char_length(title) <= 120))),
    CONSTRAINT skills_visibility_check CHECK ((visibility = ANY (ARRAY['private'::text, 'public'::text])))
);


--
-- Name: skills_id_seq; Type: SEQUENCE; Schema: community; Owner: -
--

ALTER TABLE community.skills ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME community.skills_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: system_config; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.system_config (
    namespace text NOT NULL,
    key text NOT NULL,
    value jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_api_tokens; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.user_api_tokens (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    name text NOT NULL,
    token_hash bytea NOT NULL,
    token_prefix text NOT NULL,
    scopes text[] DEFAULT ARRAY['read'::text, 'reaction:write'::text, 'skill:write'::text] NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone,
    last_used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    token_plain text,
    CONSTRAINT user_api_tokens_name_check CHECK (((char_length(name) >= 1) AND (char_length(name) <= 80))),
    CONSTRAINT user_api_tokens_scopes_check CHECK ((scopes <@ ARRAY['read'::text, 'reaction:write'::text, 'skill:write'::text]))
);


--
-- Name: user_api_tokens_id_seq; Type: SEQUENCE; Schema: community; Owner: -
--

ALTER TABLE community.user_api_tokens ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME community.user_api_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: user_follows; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.user_follows (
    follower_user_id bigint NOT NULL,
    followed_user_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT user_follows_check CHECK ((follower_user_id <> followed_user_id))
);


--
-- Name: users; Type: TABLE; Schema: community; Owner: -
--

CREATE TABLE community.users (
    id bigint NOT NULL,
    username text NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    role text DEFAULT 'member'::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    display_name text NOT NULL,
    bio text,
    avatar_path text,
    avatar_version text,
    email_verified_at timestamp with time zone,
    last_login_at timestamp with time zone,
    location text,
    institution text,
    title text,
    website text,
    orcid text,
    CONSTRAINT users_bio_length CHECK (((bio IS NULL) OR (char_length(bio) <= 500))),
    CONSTRAINT users_display_name_length CHECK (((char_length(display_name) >= 1) AND (char_length(display_name) <= 80))),
    CONSTRAINT users_role_check CHECK ((role = ANY (ARRAY['member'::text, 'admin'::text]))),
    CONSTRAINT users_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text])))
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: community; Owner: -
--

ALTER TABLE community.users ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME community.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: chemicals_import_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.chemicals_import_meta (
    singleton boolean DEFAULT true NOT NULL,
    source_path text NOT NULL,
    source_sha256 text NOT NULL,
    expected_rows bigint NOT NULL,
    loaded_rows bigint DEFAULT 0 NOT NULL,
    canonicalized_rows bigint DEFAULT 0 NOT NULL,
    failed_rows bigint DEFAULT 0 NOT NULL,
    last_cid integer DEFAULT 0 NOT NULL,
    rdkit_version text NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    identifiers_source_path text,
    identifiers_source_sha256 text,
    identifiers_expected_counts jsonb,
    identifiers_loaded_cids bigint DEFAULT 0 NOT NULL,
    identifiers_loaded_values bigint DEFAULT 0 NOT NULL,
    identifiers_last_cid integer DEFAULT 0 NOT NULL,
    identifiers_status text,
    identifiers_started_at timestamp with time zone,
    identifiers_updated_at timestamp with time zone,
    identifiers_completed_at timestamp with time zone,
    identifiers_rejected_counts jsonb,
    identifiers_orphan_cids bigint DEFAULT 0 NOT NULL,
    identifiers_orphan_values bigint DEFAULT 0 NOT NULL,
    identifiers_orphan_counts jsonb DEFAULT '{}'::jsonb NOT NULL,
    identifiers_orphan_nonnull_counts jsonb DEFAULT '{}'::jsonb NOT NULL,
    identifiers_orphan_samples jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT chemicals_import_meta_singleton_check CHECK (singleton)
);


--
-- Name: dsstox_chemical_matches; Type: TABLE; Schema: ingest; Owner: -
--

CREATE UNLOGGED TABLE ingest.dsstox_chemical_matches (
    source_row bigint NOT NULL,
    pubchem_cid integer NOT NULL,
    dtxsid text NOT NULL,
    preferred_name text NOT NULL,
    iupac_name text,
    molecular_formula text NOT NULL,
    average_mass double precision NOT NULL,
    monoisotopic_mass double precision NOT NULL,
    inchikey text NOT NULL,
    source_casrn text NOT NULL,
    source_dtxcid text,
    match_method text NOT NULL,
    imported boolean DEFAULT false NOT NULL
);


--
-- Name: dsstox_import_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.dsstox_import_meta (
    singleton boolean DEFAULT true NOT NULL,
    source_path text NOT NULL,
    source_sha256 text NOT NULL,
    expected_rows bigint NOT NULL,
    last_source_row bigint DEFAULT 0 NOT NULL,
    status text NOT NULL,
    stats jsonb DEFAULT '{}'::jsonb NOT NULL,
    rdkit_version text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    matched_at timestamp with time zone,
    completed_at timestamp with time zone,
    CONSTRAINT dsstox_import_meta_singleton_check CHECK (singleton)
);


--
-- Name: dsstox_reconcile_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.dsstox_reconcile_meta (
    singleton boolean DEFAULT true NOT NULL,
    source_sha256 text NOT NULL,
    source_rows bigint NOT NULL,
    initial_residual_rows bigint NOT NULL,
    stats jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text NOT NULL,
    rdkit_version text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT dsstox_reconcile_meta_singleton_check CHECK (singleton)
);


--
-- Name: dsstox_residual_cas_classification; Type: TABLE; Schema: ingest; Owner: -
--

CREATE UNLOGGED TABLE ingest.dsstox_residual_cas_classification (
    source_row integer NOT NULL,
    pubchem_cid integer NOT NULL,
    target_dtxsid text,
    source_kind text NOT NULL,
    candidate_has_structure boolean NOT NULL,
    exact_smiles boolean NOT NULL,
    full_inchikey boolean NOT NULL,
    same_connectivity boolean NOT NULL,
    same_fragment_parent boolean,
    same_charge_parent boolean,
    same_tautomer_parent boolean
);


--
-- Name: dsstox_residual_exact_candidates; Type: TABLE; Schema: ingest; Owner: -
--

CREATE UNLOGGED TABLE ingest.dsstox_residual_exact_candidates (
    source_row integer,
    dtxsid text,
    pubchem_cid integer,
    target_dtxsid text
);


--
-- Name: dsstox_residual_exact_safe; Type: TABLE; Schema: ingest; Owner: -
--

CREATE UNLOGGED TABLE ingest.dsstox_residual_exact_safe (
    source_row integer NOT NULL,
    pubchem_cid integer
);


--
-- Name: dsstox_residual_stage; Type: TABLE; Schema: ingest; Owner: -
--

CREATE UNLOGGED TABLE ingest.dsstox_residual_stage (
    source_row integer NOT NULL,
    dtxsid text NOT NULL,
    preferred_name text NOT NULL,
    casrn text,
    cas_is_valid boolean NOT NULL,
    dtxcid text,
    source_inchikey text,
    iupac_name text,
    source_smiles text,
    canonical_smiles text,
    calculated_inchikey text,
    connectivity_key text,
    calculated_formula text,
    calculated_average_mass double precision,
    calculated_monoisotopic_mass double precision,
    source_formula text,
    source_average_mass double precision,
    source_monoisotopic_mass double precision
);


--
-- Name: occurrence_chemical_migration_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.occurrence_chemical_migration_meta (
    key text NOT NULL,
    value text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: rdkit_mol_absorption_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.rdkit_mol_absorption_meta (
    singleton boolean DEFAULT true NOT NULL,
    status text NOT NULL,
    unmatched_before bigint,
    distinct_structures bigint,
    inserted_chemicals bigint,
    mapped_mols bigint,
    first_chemical_id integer,
    last_chemical_id integer,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT rdkit_mol_absorption_meta_singleton_check CHECK (singleton)
);


--
-- Name: rdkit_mol_chemical_map; Type: TABLE; Schema: ingest; Owner: -
--

CREATE UNLOGGED TABLE ingest.rdkit_mol_chemical_map (
    rdkit_mol_id integer NOT NULL,
    chemical_id integer,
    match_method text,
    candidate_count integer,
    has_dsstox boolean,
    evidence_score smallint
);


--
-- Name: rdkit_mol_migration_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.rdkit_mol_migration_meta (
    singleton boolean DEFAULT true NOT NULL,
    status text NOT NULL,
    rdkit_extension_version text,
    source_mols bigint,
    candidate_rows bigint,
    matched_mols bigint,
    unmatched_mols bigint,
    ambiguous_mols bigint,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT rdkit_mol_migration_meta_singleton_check CHECK (singleton)
);


--
-- Name: rdkit_mol_payload_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.rdkit_mol_payload_meta (
    singleton boolean DEFAULT true NOT NULL,
    status text NOT NULL,
    target_rows bigint,
    copied_rows bigint DEFAULT 0 NOT NULL,
    last_chemical_id integer DEFAULT 0 NOT NULL,
    batch_rows integer,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT rdkit_mol_payload_meta_singleton_check CHECK (singleton)
);


--
-- Name: rdkit_mol_version_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.rdkit_mol_version_meta (
    singleton boolean DEFAULT true NOT NULL,
    status text NOT NULL,
    source_mols bigint,
    changed_smiles bigint,
    changed_unmatched_before bigint,
    candidate_rows bigint,
    recovered_mols bigint,
    unmatched_after bigint,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT rdkit_mol_version_meta_singleton_check CHECK (singleton)
);


--
-- Name: reaction_rdkit_failures; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.reaction_rdkit_failures (
    reaction_id bigint NOT NULL,
    reaction_smiles text,
    attempted_at timestamp with time zone DEFAULT now() NOT NULL,
    reason text DEFAULT 'rdkit_parse_failure'::text NOT NULL
);


--
-- Name: reaction_rdkit_migration_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.reaction_rdkit_migration_meta (
    key text NOT NULL,
    value text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: reactions_migration_meta; Type: TABLE; Schema: ingest; Owner: -
--

CREATE TABLE ingest.reactions_migration_meta (
    key text NOT NULL,
    value text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: chemicalbook_seed; Type: TABLE; Schema: ingestion; Owner: -
--

CREATE TABLE ingestion.chemicalbook_seed (
    cb_number text NOT NULL,
    cas text NOT NULL,
    status text DEFAULT 'ACCEPTED'::text NOT NULL,
    last_chemical_id bigint,
    attempts integer DEFAULT 0 NOT NULL,
    last_error text,
    enqueued_at timestamp with time zone,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chemicalbook_seed_status_check CHECK ((status = ANY (ARRAY['ACCEPTED'::text, 'RESOLVED_EXISTING'::text, 'PENDING_NEW'::text, 'AMBIGUOUS'::text, 'CONFLICT'::text, 'ENQUEUED'::text, 'ERROR'::text])))
);


--
-- Name: chemical_identity_redirect; Type: TABLE; Schema: maintenance; Owner: -
--

CREATE TABLE maintenance.chemical_identity_redirect (
    old_chemical_id bigint NOT NULL,
    canonical_chemical_id bigint NOT NULL,
    merge_log_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE chemical_identity_redirect; Type: COMMENT; Schema: maintenance; Owner: -
--

COMMENT ON TABLE maintenance.chemical_identity_redirect IS '旧 chemical_id → canonical 映射; canonicalize_id 查询, merge_log 管审计本表管运行时兼容';


--
-- Name: v_seed_enrichment_outcome; Type: VIEW; Schema: ingestion; Owner: -
--

CREATE VIEW ingestion.v_seed_enrichment_outcome AS
 SELECT s.cb_number,
    s.cas,
    s.status AS seed_status,
    s.last_chemical_id AS recorded_chemical_id,
    COALESCE(r.canonical_chemical_id, s.last_chemical_id) AS current_chemical_id,
    (r.canonical_chemical_id IS NOT NULL) AS recorded_id_was_stale,
    cb.last_status AS cb_last_status,
    (cb.last_status = 'ok'::text) AS cb_ok,
    (cb.last_status = 'not_found'::text) AS cb_not_found,
    (c.mol IS NOT NULL) AS has_mol,
    (c.inchikey IS NOT NULL) AS has_inchikey,
    (c.pubchem_cid IS NOT NULL) AS has_pubchem_cid,
    ((c.mol IS NOT NULL) OR (c.inchikey IS NOT NULL) OR (c.pubchem_cid IS NOT NULL) OR (cb.last_status = 'ok'::text)) AS enriched
   FROM (((ingestion.chemicalbook_seed s
     LEFT JOIN maintenance.chemical_identity_redirect r ON ((r.old_chemical_id = s.last_chemical_id)))
     LEFT JOIN chemistry.chemical_cb cb ON (((cb.chemical_id = COALESCE(r.canonical_chemical_id, s.last_chemical_id)) AND (cb.locale = 'zh-CN'::text))))
     LEFT JOIN chemistry.chemicals c ON ((c.id = COALESCE(r.canonical_chemical_id, s.last_chemical_id))));


--
-- Name: cas_jobs; Type: TABLE; Schema: maintenance; Owner: -
--

CREATE TABLE maintenance.cas_jobs (
    id bigint NOT NULL,
    chemical_id integer,
    cas_number text NOT NULL,
    priority smallint DEFAULT 50 NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    dedupe_key text NOT NULL,
    request_context jsonb DEFAULT '{}'::jsonb NOT NULL,
    lease_owner text,
    lease_token_hash bytea,
    lease_expires_at timestamp with time zone,
    last_error_code text,
    last_error_detail text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT cas_jobs_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'leased'::text, 'error'::text])))
);


--
-- Name: cas_jobs_id_seq; Type: SEQUENCE; Schema: maintenance; Owner: -
--

ALTER TABLE maintenance.cas_jobs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME maintenance.cas_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cb_negative_observations; Type: TABLE; Schema: maintenance; Owner: -
--

CREATE TABLE maintenance.cb_negative_observations (
    negative_key text NOT NULL,
    kind text NOT NULL,
    cas_number text,
    cb_number text,
    locale text,
    first_observed_at timestamp with time zone DEFAULT now() NOT NULL,
    observed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT cb_negative_cas_locator_shape_check CHECK (((kind <> 'cas_locator'::text) OR ((cas_number IS NOT NULL) AND (cb_number IS NULL) AND (locale IS NULL)))),
    CONSTRAINT cb_negative_kind_check CHECK ((kind = ANY (ARRAY['cas_locator'::text, 'locale_variant'::text]))),
    CONSTRAINT cb_negative_locale_variant_shape_check CHECK (((kind <> 'locale_variant'::text) OR ((cb_number IS NOT NULL) AND (locale IS NOT NULL) AND (cas_number IS NULL))))
);


--
-- Name: identity_merge_log; Type: TABLE; Schema: maintenance; Owner: -
--

CREATE TABLE maintenance.identity_merge_log (
    merge_id bigint NOT NULL,
    source_id bigint NOT NULL,
    target_id bigint NOT NULL,
    reason text NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_keys_before jsonb DEFAULT '{}'::jsonb NOT NULL,
    target_keys_before jsonb DEFAULT '{}'::jsonb NOT NULL,
    trigger text,
    merged_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE identity_merge_log; Type: COMMENT; Schema: maintenance; Owner: -
--

COMMENT ON TABLE maintenance.identity_merge_log IS '身份合并审计: absorb 前落表, 含两侧 before snapshot(JSONB), 回滚/复查依据';


--
-- Name: COLUMN identity_merge_log.source_id; Type: COMMENT; Schema: maintenance; Owner: -
--

COMMENT ON COLUMN maintenance.identity_merge_log.source_id IS '被吸收并删除的行 id (经 redirect 仍可追溯)';


--
-- Name: identity_merge_log_merge_id_seq; Type: SEQUENCE; Schema: maintenance; Owner: -
--

CREATE SEQUENCE maintenance.identity_merge_log_merge_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: identity_merge_log_merge_id_seq; Type: SEQUENCE OWNED BY; Schema: maintenance; Owner: -
--

ALTER SEQUENCE maintenance.identity_merge_log_merge_id_seq OWNED BY maintenance.identity_merge_log.merge_id;


--
-- Name: pubchem_identity_jobs; Type: TABLE; Schema: maintenance; Owner: -
--

CREATE TABLE maintenance.pubchem_identity_jobs (
    id bigint NOT NULL,
    chemical_id integer NOT NULL,
    evidence_type text NOT NULL,
    evidence_value text NOT NULL,
    evidence_hash text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    priority integer DEFAULT 60 NOT NULL,
    dedupe_key text NOT NULL,
    result jsonb,
    request_context jsonb,
    last_error_code text,
    last_error_detail text,
    lease_owner text,
    lease_token_hash bytea,
    lease_expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: pubchem_identity_jobs_id_seq; Type: SEQUENCE; Schema: maintenance; Owner: -
--

ALTER TABLE maintenance.pubchem_identity_jobs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME maintenance.pubchem_identity_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: pubchem_job_events; Type: TABLE; Schema: maintenance; Owner: -
--

CREATE TABLE maintenance.pubchem_job_events (
    id bigint NOT NULL,
    job_id bigint NOT NULL,
    worker_id text,
    event_type text NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pubchem_job_events_details_object CHECK ((jsonb_typeof(details) = 'object'::text)),
    CONSTRAINT pubchem_job_events_event_type_check CHECK ((event_type = ANY (ARRAY['queued'::text, 'leased'::text, 'heartbeat'::text, 'succeeded'::text, 'retry'::text, 'failed'::text, 'dead'::text])))
);


--
-- Name: pubchem_job_events_id_seq; Type: SEQUENCE; Schema: maintenance; Owner: -
--

ALTER TABLE maintenance.pubchem_job_events ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME maintenance.pubchem_job_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: pubchem_jobs; Type: TABLE; Schema: maintenance; Owner: -
--

CREATE TABLE maintenance.pubchem_jobs (
    id bigint NOT NULL,
    chemical_id integer,
    query_value text NOT NULL,
    priority smallint DEFAULT 50 NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    dedupe_key text NOT NULL,
    requested_by_user_id bigint,
    request_context jsonb DEFAULT '{}'::jsonb NOT NULL,
    lease_owner text,
    lease_token_hash bytea,
    lease_expires_at timestamp with time zone,
    last_error_code text,
    last_error_detail text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pubchem_jobs_lease_shape CHECK (((status <> 'leased'::text) OR ((lease_owner IS NOT NULL) AND (lease_token_hash IS NOT NULL) AND (lease_expires_at IS NOT NULL)))),
    CONSTRAINT pubchem_jobs_priority_check CHECK (((priority >= 0) AND (priority <= 100))),
    CONSTRAINT pubchem_jobs_query_value_check CHECK (((length(query_value) >= 1) AND (length(query_value) <= 4000))),
    CONSTRAINT pubchem_jobs_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'leased'::text, 'error'::text])))
);


--
-- Name: pubchem_jobs_id_seq; Type: SEQUENCE; Schema: maintenance; Owner: -
--

ALTER TABLE maintenance.pubchem_jobs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME maintenance.pubchem_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: worker_clients; Type: TABLE; Schema: maintenance; Owner: -
--

CREATE TABLE maintenance.worker_clients (
    worker_id text NOT NULL,
    display_name text NOT NULL,
    token_hash bytea NOT NULL,
    token_prefix text NOT NULL,
    scopes text[] DEFAULT ARRAY['pubchem'::text] NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    max_lease_jobs smallint DEFAULT 4 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone,
    disabled_at timestamp with time zone,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT worker_clients_max_lease_jobs_check CHECK (((max_lease_jobs >= 1) AND (max_lease_jobs <= 20))),
    CONSTRAINT worker_clients_metadata_object CHECK ((jsonb_typeof(metadata) = 'object'::text))
);


--
-- Name: addition_device; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.addition_device (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."AdditionDeviceType",
    details text,
    reaction_input_id integer
);


--
-- Name: addition_device_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.addition_device_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: addition_device_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.addition_device_id_seq OWNED BY ord.addition_device.id;


--
-- Name: addition_speed; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.addition_speed (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."AdditionSpeedType",
    details text,
    reaction_input_id integer
);


--
-- Name: addition_speed_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.addition_speed_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: addition_speed_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.addition_speed_id_seq OWNED BY ord.addition_speed.id;


--
-- Name: amount; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.amount (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    volume_includes_solutes boolean,
    reaction_workup_id integer,
    compound_id integer,
    crude_component_id integer,
    product_measurement_id integer
);


--
-- Name: amount_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.amount_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: amount_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.amount_id_seq OWNED BY ord.amount.id;


--
-- Name: analysis; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.analysis (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    key text,
    type public."AnalysisType",
    details text,
    chmo_id integer,
    is_of_isolated_species boolean,
    instrument_manufacturer text,
    reaction_outcome_id integer,
    compound_id integer
);


--
-- Name: analysis_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.analysis_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: analysis_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.analysis_id_seq OWNED BY ord.analysis.id;


--
-- Name: atmosphere; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.atmosphere (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."AtmosphereType",
    details text,
    pressure_conditions_id integer
);


--
-- Name: atmosphere_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.atmosphere_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: atmosphere_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.atmosphere_id_seq OWNED BY ord.atmosphere.id;


--
-- Name: compound; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.compound (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    reaction_role public."ReactionRoleType",
    is_limiting boolean,
    smiles text,
    chemical_id integer,
    product_measurement_id integer,
    reaction_input_id integer
);


--
-- Name: compound_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.compound_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: compound_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.compound_id_seq OWNED BY ord.compound.id;


--
-- Name: compound_preparation; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.compound_preparation (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."CompoundPreparationType",
    details text,
    reaction_id text,
    compound_id integer
);


--
-- Name: compound_preparation_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.compound_preparation_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: compound_preparation_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.compound_preparation_id_seq OWNED BY ord.compound_preparation.id;


--
-- Name: crude_component; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.crude_component (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    reaction_id text NOT NULL,
    includes_workup boolean,
    has_derived_amount boolean,
    reaction_input_id integer
);


--
-- Name: crude_component_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.crude_component_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crude_component_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.crude_component_id_seq OWNED BY ord.crude_component.id;


--
-- Name: current; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.current (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."CurrentUnit",
    electrochemistry_conditions_id integer,
    electrochemistry_measurement_id integer
);


--
-- Name: current_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.current_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: current_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.current_id_seq OWNED BY ord.current.id;


--
-- Name: data; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.data (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    key text,
    float_value double precision,
    integer_value integer,
    bytes_value bytea,
    string_value text,
    url text,
    description text,
    format text,
    reaction_provenance_id integer,
    reaction_setup_id integer,
    reaction_observation_id integer,
    analysis_id integer,
    product_compound_id integer,
    compound_id integer
);


--
-- Name: data_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.data_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.data_id_seq OWNED BY ord.data.id;


--
-- Name: dataset; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.dataset (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    name text,
    description text,
    reaction_ids text[],
    dataset_id text NOT NULL,
    md5 character varying(32) NOT NULL,
    num_reactions integer NOT NULL,
    submitted_at date
);


--
-- Name: dataset_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.dataset_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dataset_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.dataset_id_seq OWNED BY ord.dataset.id;


--
-- Name: date_time; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.date_time (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value text,
    analysis_id integer,
    record_event_id integer,
    reaction_provenance_id integer
);


--
-- Name: date_time_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.date_time_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: date_time_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.date_time_id_seq OWNED BY ord.date_time.id;


--
-- Name: electrochemistry_cell; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.electrochemistry_cell (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."ElectrochemistryCellType",
    details text,
    electrochemistry_conditions_id integer
);


--
-- Name: electrochemistry_cell_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.electrochemistry_cell_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: electrochemistry_cell_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.electrochemistry_cell_id_seq OWNED BY ord.electrochemistry_cell.id;


--
-- Name: electrochemistry_conditions; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.electrochemistry_conditions (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."ElectrochemistryType",
    details text,
    anode_material text,
    cathode_material text,
    reaction_conditions_id integer
);


--
-- Name: electrochemistry_conditions_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.electrochemistry_conditions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: electrochemistry_conditions_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.electrochemistry_conditions_id_seq OWNED BY ord.electrochemistry_conditions.id;


--
-- Name: electrochemistry_measurement; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.electrochemistry_measurement (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    electrochemistry_conditions_id integer
);


--
-- Name: electrochemistry_measurement_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.electrochemistry_measurement_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: electrochemistry_measurement_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.electrochemistry_measurement_id_seq OWNED BY ord.electrochemistry_measurement.id;


--
-- Name: float_value; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.float_value (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    product_measurement_id integer
);


--
-- Name: float_value_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.float_value_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: float_value_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.float_value_id_seq OWNED BY ord.float_value.id;


--
-- Name: flow_conditions; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.flow_conditions (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."FlowType",
    details text,
    pump_type text,
    reaction_conditions_id integer
);


--
-- Name: flow_conditions_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.flow_conditions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: flow_conditions_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.flow_conditions_id_seq OWNED BY ord.flow_conditions.id;


--
-- Name: flow_rate; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.flow_rate (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."FlowRateUnit",
    reaction_input_id integer
);


--
-- Name: flow_rate_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.flow_rate_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: flow_rate_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.flow_rate_id_seq OWNED BY ord.flow_rate.id;


--
-- Name: illumination_conditions; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.illumination_conditions (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."IlluminationType",
    details text,
    color text,
    reaction_conditions_id integer
);


--
-- Name: illumination_conditions_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.illumination_conditions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: illumination_conditions_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.illumination_conditions_id_seq OWNED BY ord.illumination_conditions.id;


--
-- Name: length; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.length (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."LengthUnit",
    electrochemistry_conditions_id integer,
    tubing_id integer,
    illumination_conditions_id integer
);


--
-- Name: length_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.length_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: length_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.length_id_seq OWNED BY ord.length.id;


--
-- Name: mass; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.mass (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."MassUnit",
    amount_id integer
);


--
-- Name: mass_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.mass_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mass_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.mass_id_seq OWNED BY ord.mass.id;


--
-- Name: mass_spec_measurement_details; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.mass_spec_measurement_details (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."MassSpecMeasurementType",
    details text,
    tic_minimum_mz double precision,
    tic_maximum_mz double precision,
    eic_masses double precision[],
    product_measurement_id integer
);


--
-- Name: mass_spec_measurement_details_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.mass_spec_measurement_details_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mass_spec_measurement_details_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.mass_spec_measurement_details_id_seq OWNED BY ord.mass_spec_measurement_details.id;


--
-- Name: moles; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.moles (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."MolesUnit",
    amount_id integer
);


--
-- Name: moles_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.moles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: moles_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.moles_id_seq OWNED BY ord.moles.id;


--
-- Name: percentage; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.percentage (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    reaction_outcome_id integer,
    product_measurement_id integer
);


--
-- Name: percentage_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.percentage_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: percentage_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.percentage_id_seq OWNED BY ord.percentage.id;


--
-- Name: person; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.person (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    username text,
    name text,
    orcid text,
    organization text,
    email text,
    reaction_provenance_id integer,
    record_event_id integer
);


--
-- Name: person_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.person_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: person_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.person_id_seq OWNED BY ord.person.id;


--
-- Name: pressure; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.pressure (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."PressureUnit",
    pressure_conditions_id integer,
    pressure_measurement_id integer
);


--
-- Name: pressure_conditions; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.pressure_conditions (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    reaction_conditions_id integer
);


--
-- Name: pressure_conditions_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.pressure_conditions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pressure_conditions_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.pressure_conditions_id_seq OWNED BY ord.pressure_conditions.id;


--
-- Name: pressure_control; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.pressure_control (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."PressureControlType",
    details text,
    pressure_conditions_id integer
);


--
-- Name: pressure_control_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.pressure_control_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pressure_control_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.pressure_control_id_seq OWNED BY ord.pressure_control.id;


--
-- Name: pressure_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.pressure_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pressure_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.pressure_id_seq OWNED BY ord.pressure.id;


--
-- Name: pressure_measurement; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.pressure_measurement (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."PressureMeasurementType",
    details text,
    pressure_conditions_id integer
);


--
-- Name: pressure_measurement_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.pressure_measurement_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pressure_measurement_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.pressure_measurement_id_seq OWNED BY ord.pressure_measurement.id;


--
-- Name: product_compound; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.product_compound (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    is_desired_product boolean,
    isolated_color text,
    reaction_role public."ReactionRoleType",
    smiles text,
    chemical_id integer,
    reaction_outcome_id integer
);


--
-- Name: product_compound_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.product_compound_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: product_compound_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.product_compound_id_seq OWNED BY ord.product_compound.id;


--
-- Name: product_measurement; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.product_measurement (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    analysis_key text,
    type public."ProductMeasurementType",
    details text,
    uses_internal_standard boolean,
    is_normalized boolean,
    uses_authentic_standard boolean,
    string_value text,
    product_compound_id integer
);


--
-- Name: product_measurement_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.product_measurement_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: product_measurement_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.product_measurement_id_seq OWNED BY ord.product_measurement.id;


--
-- Name: reaction; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction (
    id integer NOT NULL,
    reaction_id text NOT NULL,
    reaction_smiles text,
    dataset_id integer
);


--
-- Name: reaction_conditions; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_conditions (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    reflux boolean,
    ph double precision,
    conditions_are_dynamic boolean,
    details text,
    reaction_id integer
);


--
-- Name: reaction_conditions_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_conditions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_conditions_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_conditions_id_seq OWNED BY ord.reaction_conditions.id;


--
-- Name: reaction_environment; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_environment (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."ReactionEnvironmentType",
    details text,
    reaction_setup_id integer
);


--
-- Name: reaction_environment_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_environment_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_environment_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_environment_id_seq OWNED BY ord.reaction_environment.id;


--
-- Name: reaction_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_id_seq OWNED BY ord.reaction.id;


--
-- Name: reaction_identifier; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_identifier (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."ReactionIdentifierType",
    details text,
    value text,
    is_mapped boolean,
    reaction_id integer
);


--
-- Name: reaction_identifier_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_identifier_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_identifier_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_identifier_id_seq OWNED BY ord.reaction_identifier.id;


--
-- Name: reaction_input; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_input (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    key text,
    addition_order integer,
    reaction_id integer,
    reaction_workup_id integer
);


--
-- Name: reaction_input_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_input_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_input_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_input_id_seq OWNED BY ord.reaction_input.id;


--
-- Name: reaction_map; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_map (
    ord_reaction_id integer NOT NULL,
    reaction_id bigint NOT NULL
);


--
-- Name: reaction_notes; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_notes (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    is_heterogeneous boolean,
    forms_precipitate boolean,
    is_exothermic boolean,
    offgasses boolean,
    is_sensitive_to_moisture boolean,
    is_sensitive_to_oxygen boolean,
    is_sensitive_to_light boolean,
    safety_notes text,
    procedure_details text,
    reaction_id integer
);


--
-- Name: reaction_notes_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_notes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_notes_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_notes_id_seq OWNED BY ord.reaction_notes.id;


--
-- Name: reaction_observation; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_observation (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    comment text,
    reaction_id integer
);


--
-- Name: reaction_observation_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_observation_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_observation_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_observation_id_seq OWNED BY ord.reaction_observation.id;


--
-- Name: reaction_outcome; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_outcome (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    reaction_id integer
);


--
-- Name: reaction_outcome_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_outcome_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_outcome_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_outcome_id_seq OWNED BY ord.reaction_outcome.id;


--
-- Name: reaction_provenance; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_provenance (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    city text,
    doi text,
    patent text,
    publication_url text,
    is_mined boolean,
    reaction_id integer
);


--
-- Name: reaction_provenance_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_provenance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_provenance_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_provenance_id_seq OWNED BY ord.reaction_provenance.id;


--
-- Name: reaction_setup; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_setup (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    is_automated boolean,
    automation_platform text,
    reaction_id integer
);


--
-- Name: reaction_setup_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_setup_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_setup_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_setup_id_seq OWNED BY ord.reaction_setup.id;


--
-- Name: reaction_workup; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.reaction_workup (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."ReactionWorkupType",
    details text,
    keep_phase text,
    target_ph double precision,
    is_automated boolean,
    reaction_id integer
);


--
-- Name: reaction_workup_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.reaction_workup_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reaction_workup_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.reaction_workup_id_seq OWNED BY ord.reaction_workup.id;


--
-- Name: record_event; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.record_event (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    details text,
    reaction_provenance_id integer
);


--
-- Name: record_event_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.record_event_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: record_event_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.record_event_id_seq OWNED BY ord.record_event.id;


--
-- Name: selectivity; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.selectivity (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."SelectivityType",
    details text,
    product_measurement_id integer
);


--
-- Name: selectivity_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.selectivity_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: selectivity_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.selectivity_id_seq OWNED BY ord.selectivity.id;


--
-- Name: source; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.source (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    vendor text,
    catalog_id text,
    lot text,
    compound_id integer
);


--
-- Name: source_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.source_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.source_id_seq OWNED BY ord.source.id;


--
-- Name: stirring_conditions; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.stirring_conditions (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."StirringMethodType",
    details text,
    reaction_workup_id integer,
    reaction_conditions_id integer
);


--
-- Name: stirring_conditions_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.stirring_conditions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stirring_conditions_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.stirring_conditions_id_seq OWNED BY ord.stirring_conditions.id;


--
-- Name: stirring_rate; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.stirring_rate (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."StirringRateType",
    details text,
    rpm integer,
    stirring_conditions_id integer
);


--
-- Name: stirring_rate_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.stirring_rate_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stirring_rate_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.stirring_rate_id_seq OWNED BY ord.stirring_rate.id;


--
-- Name: temperature; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.temperature (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."TemperatureUnit",
    temperature_conditions_id integer,
    reaction_input_id integer,
    temperature_measurement_id integer
);


--
-- Name: temperature_conditions; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.temperature_conditions (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    reaction_conditions_id integer,
    reaction_workup_id integer
);


--
-- Name: temperature_conditions_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.temperature_conditions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: temperature_conditions_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.temperature_conditions_id_seq OWNED BY ord.temperature_conditions.id;


--
-- Name: temperature_control; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.temperature_control (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."TemperatureControlType",
    details text,
    temperature_conditions_id integer
);


--
-- Name: temperature_control_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.temperature_control_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: temperature_control_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.temperature_control_id_seq OWNED BY ord.temperature_control.id;


--
-- Name: temperature_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.temperature_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: temperature_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.temperature_id_seq OWNED BY ord.temperature.id;


--
-- Name: temperature_measurement; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.temperature_measurement (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."TemperatureMeasurementType",
    details text,
    temperature_conditions_id integer
);


--
-- Name: temperature_measurement_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.temperature_measurement_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: temperature_measurement_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.temperature_measurement_id_seq OWNED BY ord.temperature_measurement.id;


--
-- Name: texture; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.texture (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."TextureType",
    details text,
    product_compound_id integer,
    reaction_input_id integer,
    compound_id integer,
    crude_component_id integer
);


--
-- Name: texture_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.texture_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: texture_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.texture_id_seq OWNED BY ord.texture.id;


--
-- Name: time; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord."time" (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."TimeUnit",
    temperature_measurement_id integer,
    reaction_outcome_id integer,
    reaction_input_id integer,
    reaction_workup_id integer,
    pressure_measurement_id integer,
    electrochemistry_measurement_id integer,
    product_measurement_id integer,
    reaction_observation_id integer
);


--
-- Name: time_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.time_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: time_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.time_id_seq OWNED BY ord."time".id;


--
-- Name: tubing; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.tubing (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."TubingType",
    details text,
    flow_conditions_id integer
);


--
-- Name: tubing_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.tubing_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tubing_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.tubing_id_seq OWNED BY ord.tubing.id;


--
-- Name: unmeasured_amount; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.unmeasured_amount (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."UnmeasuredAmountType",
    details text,
    amount_id integer
);


--
-- Name: unmeasured_amount_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.unmeasured_amount_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: unmeasured_amount_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.unmeasured_amount_id_seq OWNED BY ord.unmeasured_amount.id;


--
-- Name: vessel; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.vessel (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."VesselType",
    details text,
    vessel_id text,
    "position" text,
    "row" text,
    col text,
    reaction_setup_id integer
);


--
-- Name: vessel_attachment; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.vessel_attachment (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."VesselAttachmentType",
    details text,
    vessel_id integer
);


--
-- Name: vessel_attachment_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.vessel_attachment_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vessel_attachment_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.vessel_attachment_id_seq OWNED BY ord.vessel_attachment.id;


--
-- Name: vessel_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.vessel_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vessel_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.vessel_id_seq OWNED BY ord.vessel.id;


--
-- Name: vessel_material; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.vessel_material (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."VesselMaterialType",
    details text,
    vessel_id integer
);


--
-- Name: vessel_material_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.vessel_material_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vessel_material_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.vessel_material_id_seq OWNED BY ord.vessel_material.id;


--
-- Name: vessel_preparation; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.vessel_preparation (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    type public."VesselPreparationType",
    details text,
    vessel_id integer
);


--
-- Name: vessel_preparation_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.vessel_preparation_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vessel_preparation_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.vessel_preparation_id_seq OWNED BY ord.vessel_preparation.id;


--
-- Name: voltage; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.voltage (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."VoltageUnit",
    electrochemistry_conditions_id integer,
    electrochemistry_measurement_id integer
);


--
-- Name: voltage_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.voltage_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: voltage_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.voltage_id_seq OWNED BY ord.voltage.id;


--
-- Name: volume; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.volume (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."VolumeUnit",
    vessel_id integer,
    amount_id integer
);


--
-- Name: volume_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.volume_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: volume_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.volume_id_seq OWNED BY ord.volume.id;


--
-- Name: wavelength; Type: TABLE; Schema: ord; Owner: -
--

CREATE TABLE ord.wavelength (
    id integer NOT NULL,
    ord_schema_context text NOT NULL,
    value double precision,
    "precision" double precision,
    units public."WavelengthUnit",
    product_measurement_id integer,
    illumination_conditions_id integer
);


--
-- Name: wavelength_id_seq; Type: SEQUENCE; Schema: ord; Owner: -
--

CREATE SEQUENCE ord.wavelength_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wavelength_id_seq; Type: SEQUENCE OWNED BY; Schema: ord; Owner: -
--

ALTER SEQUENCE ord.wavelength_id_seq OWNED BY ord.wavelength.id;


--
-- Name: chemicals id; Type: DEFAULT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemicals ALTER COLUMN id SET DEFAULT nextval('chemistry.chemicals_id_seq'::regclass);


--
-- Name: identity_merge_log merge_id; Type: DEFAULT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.identity_merge_log ALTER COLUMN merge_id SET DEFAULT nextval('maintenance.identity_merge_log_merge_id_seq'::regclass);


--
-- Name: addition_device id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.addition_device ALTER COLUMN id SET DEFAULT nextval('ord.addition_device_id_seq'::regclass);


--
-- Name: addition_speed id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.addition_speed ALTER COLUMN id SET DEFAULT nextval('ord.addition_speed_id_seq'::regclass);


--
-- Name: amount id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.amount ALTER COLUMN id SET DEFAULT nextval('ord.amount_id_seq'::regclass);


--
-- Name: analysis id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.analysis ALTER COLUMN id SET DEFAULT nextval('ord.analysis_id_seq'::regclass);


--
-- Name: atmosphere id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.atmosphere ALTER COLUMN id SET DEFAULT nextval('ord.atmosphere_id_seq'::regclass);


--
-- Name: compound id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.compound ALTER COLUMN id SET DEFAULT nextval('ord.compound_id_seq'::regclass);


--
-- Name: compound_preparation id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.compound_preparation ALTER COLUMN id SET DEFAULT nextval('ord.compound_preparation_id_seq'::regclass);


--
-- Name: crude_component id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.crude_component ALTER COLUMN id SET DEFAULT nextval('ord.crude_component_id_seq'::regclass);


--
-- Name: current id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.current ALTER COLUMN id SET DEFAULT nextval('ord.current_id_seq'::regclass);


--
-- Name: data id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.data ALTER COLUMN id SET DEFAULT nextval('ord.data_id_seq'::regclass);


--
-- Name: dataset id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.dataset ALTER COLUMN id SET DEFAULT nextval('ord.dataset_id_seq'::regclass);


--
-- Name: date_time id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.date_time ALTER COLUMN id SET DEFAULT nextval('ord.date_time_id_seq'::regclass);


--
-- Name: electrochemistry_cell id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.electrochemistry_cell ALTER COLUMN id SET DEFAULT nextval('ord.electrochemistry_cell_id_seq'::regclass);


--
-- Name: electrochemistry_conditions id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.electrochemistry_conditions ALTER COLUMN id SET DEFAULT nextval('ord.electrochemistry_conditions_id_seq'::regclass);


--
-- Name: electrochemistry_measurement id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.electrochemistry_measurement ALTER COLUMN id SET DEFAULT nextval('ord.electrochemistry_measurement_id_seq'::regclass);


--
-- Name: float_value id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.float_value ALTER COLUMN id SET DEFAULT nextval('ord.float_value_id_seq'::regclass);


--
-- Name: flow_conditions id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.flow_conditions ALTER COLUMN id SET DEFAULT nextval('ord.flow_conditions_id_seq'::regclass);


--
-- Name: flow_rate id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.flow_rate ALTER COLUMN id SET DEFAULT nextval('ord.flow_rate_id_seq'::regclass);


--
-- Name: illumination_conditions id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.illumination_conditions ALTER COLUMN id SET DEFAULT nextval('ord.illumination_conditions_id_seq'::regclass);


--
-- Name: length id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.length ALTER COLUMN id SET DEFAULT nextval('ord.length_id_seq'::regclass);


--
-- Name: mass id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.mass ALTER COLUMN id SET DEFAULT nextval('ord.mass_id_seq'::regclass);


--
-- Name: mass_spec_measurement_details id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.mass_spec_measurement_details ALTER COLUMN id SET DEFAULT nextval('ord.mass_spec_measurement_details_id_seq'::regclass);


--
-- Name: moles id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.moles ALTER COLUMN id SET DEFAULT nextval('ord.moles_id_seq'::regclass);


--
-- Name: percentage id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.percentage ALTER COLUMN id SET DEFAULT nextval('ord.percentage_id_seq'::regclass);


--
-- Name: person id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.person ALTER COLUMN id SET DEFAULT nextval('ord.person_id_seq'::regclass);


--
-- Name: pressure id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure ALTER COLUMN id SET DEFAULT nextval('ord.pressure_id_seq'::regclass);


--
-- Name: pressure_conditions id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure_conditions ALTER COLUMN id SET DEFAULT nextval('ord.pressure_conditions_id_seq'::regclass);


--
-- Name: pressure_control id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure_control ALTER COLUMN id SET DEFAULT nextval('ord.pressure_control_id_seq'::regclass);


--
-- Name: pressure_measurement id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure_measurement ALTER COLUMN id SET DEFAULT nextval('ord.pressure_measurement_id_seq'::regclass);


--
-- Name: product_compound id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.product_compound ALTER COLUMN id SET DEFAULT nextval('ord.product_compound_id_seq'::regclass);


--
-- Name: product_measurement id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.product_measurement ALTER COLUMN id SET DEFAULT nextval('ord.product_measurement_id_seq'::regclass);


--
-- Name: reaction id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction ALTER COLUMN id SET DEFAULT nextval('ord.reaction_id_seq'::regclass);


--
-- Name: reaction_conditions id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_conditions ALTER COLUMN id SET DEFAULT nextval('ord.reaction_conditions_id_seq'::regclass);


--
-- Name: reaction_environment id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_environment ALTER COLUMN id SET DEFAULT nextval('ord.reaction_environment_id_seq'::regclass);


--
-- Name: reaction_identifier id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_identifier ALTER COLUMN id SET DEFAULT nextval('ord.reaction_identifier_id_seq'::regclass);


--
-- Name: reaction_input id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_input ALTER COLUMN id SET DEFAULT nextval('ord.reaction_input_id_seq'::regclass);


--
-- Name: reaction_notes id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_notes ALTER COLUMN id SET DEFAULT nextval('ord.reaction_notes_id_seq'::regclass);


--
-- Name: reaction_observation id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_observation ALTER COLUMN id SET DEFAULT nextval('ord.reaction_observation_id_seq'::regclass);


--
-- Name: reaction_outcome id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_outcome ALTER COLUMN id SET DEFAULT nextval('ord.reaction_outcome_id_seq'::regclass);


--
-- Name: reaction_provenance id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_provenance ALTER COLUMN id SET DEFAULT nextval('ord.reaction_provenance_id_seq'::regclass);


--
-- Name: reaction_setup id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_setup ALTER COLUMN id SET DEFAULT nextval('ord.reaction_setup_id_seq'::regclass);


--
-- Name: reaction_workup id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_workup ALTER COLUMN id SET DEFAULT nextval('ord.reaction_workup_id_seq'::regclass);


--
-- Name: record_event id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.record_event ALTER COLUMN id SET DEFAULT nextval('ord.record_event_id_seq'::regclass);


--
-- Name: selectivity id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.selectivity ALTER COLUMN id SET DEFAULT nextval('ord.selectivity_id_seq'::regclass);


--
-- Name: source id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.source ALTER COLUMN id SET DEFAULT nextval('ord.source_id_seq'::regclass);


--
-- Name: stirring_conditions id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.stirring_conditions ALTER COLUMN id SET DEFAULT nextval('ord.stirring_conditions_id_seq'::regclass);


--
-- Name: stirring_rate id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.stirring_rate ALTER COLUMN id SET DEFAULT nextval('ord.stirring_rate_id_seq'::regclass);


--
-- Name: temperature id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature ALTER COLUMN id SET DEFAULT nextval('ord.temperature_id_seq'::regclass);


--
-- Name: temperature_conditions id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_conditions ALTER COLUMN id SET DEFAULT nextval('ord.temperature_conditions_id_seq'::regclass);


--
-- Name: temperature_control id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_control ALTER COLUMN id SET DEFAULT nextval('ord.temperature_control_id_seq'::regclass);


--
-- Name: temperature_measurement id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_measurement ALTER COLUMN id SET DEFAULT nextval('ord.temperature_measurement_id_seq'::regclass);


--
-- Name: texture id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.texture ALTER COLUMN id SET DEFAULT nextval('ord.texture_id_seq'::regclass);


--
-- Name: time id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time" ALTER COLUMN id SET DEFAULT nextval('ord.time_id_seq'::regclass);


--
-- Name: tubing id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.tubing ALTER COLUMN id SET DEFAULT nextval('ord.tubing_id_seq'::regclass);


--
-- Name: unmeasured_amount id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.unmeasured_amount ALTER COLUMN id SET DEFAULT nextval('ord.unmeasured_amount_id_seq'::regclass);


--
-- Name: vessel id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel ALTER COLUMN id SET DEFAULT nextval('ord.vessel_id_seq'::regclass);


--
-- Name: vessel_attachment id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel_attachment ALTER COLUMN id SET DEFAULT nextval('ord.vessel_attachment_id_seq'::regclass);


--
-- Name: vessel_material id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel_material ALTER COLUMN id SET DEFAULT nextval('ord.vessel_material_id_seq'::regclass);


--
-- Name: vessel_preparation id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel_preparation ALTER COLUMN id SET DEFAULT nextval('ord.vessel_preparation_id_seq'::regclass);


--
-- Name: voltage id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.voltage ALTER COLUMN id SET DEFAULT nextval('ord.voltage_id_seq'::regclass);


--
-- Name: volume id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.volume ALTER COLUMN id SET DEFAULT nextval('ord.volume_id_seq'::regclass);


--
-- Name: wavelength id; Type: DEFAULT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.wavelength ALTER COLUMN id SET DEFAULT nextval('ord.wavelength_id_seq'::regclass);


--
-- Name: chemical_cb chemical_cb_pkey; Type: CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemical_cb
    ADD CONSTRAINT chemical_cb_pkey PRIMARY KEY (id);


--
-- Name: chemical_pubchem chemical_pubchem_pkey; Type: CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemical_pubchem
    ADD CONSTRAINT chemical_pubchem_pkey PRIMARY KEY (chemical_id);


--
-- Name: chemical_supplier_listing chemical_supplier_listing_pkey; Type: CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemical_supplier_listing
    ADD CONSTRAINT chemical_supplier_listing_pkey PRIMARY KEY (chemical_id, cbsid);


--
-- Name: chemical_supplier_profile chemical_supplier_profile_pkey; Type: CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemical_supplier_profile
    ADD CONSTRAINT chemical_supplier_profile_pkey PRIMARY KEY (cbsid);


--
-- Name: chemicals chemicals_pkey; Type: CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemicals
    ADD CONSTRAINT chemicals_pkey PRIMARY KEY (id);


--
-- Name: name_index name_index_pkey; Type: CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.name_index
    ADD CONSTRAINT name_index_pkey PRIMARY KEY (chemical_id, source, kind, normalized);


--
-- Name: reaction_chemicals reaction_chemicals_pkey; Type: CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.reaction_chemicals
    ADD CONSTRAINT reaction_chemicals_pkey PRIMARY KEY (reaction_id, chemical_id, role);


--
-- Name: reactions reactions_pkey; Type: CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.reactions
    ADD CONSTRAINT reactions_pkey PRIMARY KEY (id);


--
-- Name: statistics statistics_pkey; Type: CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.statistics
    ADD CONSTRAINT statistics_pkey PRIMARY KEY (metric);


--
-- Name: chemical_follows chemical_follows_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.chemical_follows
    ADD CONSTRAINT chemical_follows_pkey PRIMARY KEY (user_id, chemical_id);


--
-- Name: notifications notifications_dedupe_key_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.notifications
    ADD CONSTRAINT notifications_dedupe_key_key UNIQUE (dedupe_key);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: reaction_follows reaction_follows_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.reaction_follows
    ADD CONSTRAINT reaction_follows_pkey PRIMARY KEY (user_id, reaction_id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_token_hash_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.sessions
    ADD CONSTRAINT sessions_token_hash_key UNIQUE (token_hash);


--
-- Name: skill_categories skill_categories_name_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.skill_categories
    ADD CONSTRAINT skill_categories_name_key UNIQUE (name);


--
-- Name: skill_categories skill_categories_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.skill_categories
    ADD CONSTRAINT skill_categories_pkey PRIMARY KEY (id);


--
-- Name: skill_files skill_files_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.skill_files
    ADD CONSTRAINT skill_files_pkey PRIMARY KEY (id);


--
-- Name: skills skills_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (id);


--
-- Name: system_config system_config_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.system_config
    ADD CONSTRAINT system_config_pkey PRIMARY KEY (namespace, key);


--
-- Name: user_api_tokens user_api_tokens_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.user_api_tokens
    ADD CONSTRAINT user_api_tokens_pkey PRIMARY KEY (id);


--
-- Name: user_api_tokens user_api_tokens_token_hash_key; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.user_api_tokens
    ADD CONSTRAINT user_api_tokens_token_hash_key UNIQUE (token_hash);


--
-- Name: user_follows user_follows_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.user_follows
    ADD CONSTRAINT user_follows_pkey PRIMARY KEY (follower_user_id, followed_user_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: chemicals_import_meta chemicals_import_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.chemicals_import_meta
    ADD CONSTRAINT chemicals_import_meta_pkey PRIMARY KEY (singleton);


--
-- Name: dsstox_chemical_matches dsstox_chemical_matches_dtxsid_key; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.dsstox_chemical_matches
    ADD CONSTRAINT dsstox_chemical_matches_dtxsid_key UNIQUE (dtxsid);


--
-- Name: dsstox_chemical_matches dsstox_chemical_matches_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.dsstox_chemical_matches
    ADD CONSTRAINT dsstox_chemical_matches_pkey PRIMARY KEY (source_row);


--
-- Name: dsstox_import_meta dsstox_import_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.dsstox_import_meta
    ADD CONSTRAINT dsstox_import_meta_pkey PRIMARY KEY (singleton);


--
-- Name: dsstox_reconcile_meta dsstox_reconcile_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.dsstox_reconcile_meta
    ADD CONSTRAINT dsstox_reconcile_meta_pkey PRIMARY KEY (singleton);


--
-- Name: dsstox_residual_cas_classification dsstox_residual_cas_classification_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.dsstox_residual_cas_classification
    ADD CONSTRAINT dsstox_residual_cas_classification_pkey PRIMARY KEY (source_row, pubchem_cid);


--
-- Name: dsstox_residual_exact_safe dsstox_residual_exact_safe_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.dsstox_residual_exact_safe
    ADD CONSTRAINT dsstox_residual_exact_safe_pkey PRIMARY KEY (source_row);


--
-- Name: dsstox_residual_exact_safe dsstox_residual_exact_safe_pubchem_cid_key; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.dsstox_residual_exact_safe
    ADD CONSTRAINT dsstox_residual_exact_safe_pubchem_cid_key UNIQUE (pubchem_cid);


--
-- Name: dsstox_residual_stage dsstox_residual_stage_dtxsid_key; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.dsstox_residual_stage
    ADD CONSTRAINT dsstox_residual_stage_dtxsid_key UNIQUE (dtxsid);


--
-- Name: dsstox_residual_stage dsstox_residual_stage_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.dsstox_residual_stage
    ADD CONSTRAINT dsstox_residual_stage_pkey PRIMARY KEY (source_row);


--
-- Name: occurrence_chemical_migration_meta occurrence_chemical_migration_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.occurrence_chemical_migration_meta
    ADD CONSTRAINT occurrence_chemical_migration_meta_pkey PRIMARY KEY (key);


--
-- Name: rdkit_mol_absorption_meta rdkit_mol_absorption_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.rdkit_mol_absorption_meta
    ADD CONSTRAINT rdkit_mol_absorption_meta_pkey PRIMARY KEY (singleton);


--
-- Name: rdkit_mol_chemical_map rdkit_mol_chemical_map_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.rdkit_mol_chemical_map
    ADD CONSTRAINT rdkit_mol_chemical_map_pkey PRIMARY KEY (rdkit_mol_id);


--
-- Name: rdkit_mol_migration_meta rdkit_mol_migration_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.rdkit_mol_migration_meta
    ADD CONSTRAINT rdkit_mol_migration_meta_pkey PRIMARY KEY (singleton);


--
-- Name: rdkit_mol_payload_meta rdkit_mol_payload_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.rdkit_mol_payload_meta
    ADD CONSTRAINT rdkit_mol_payload_meta_pkey PRIMARY KEY (singleton);


--
-- Name: rdkit_mol_version_meta rdkit_mol_version_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.rdkit_mol_version_meta
    ADD CONSTRAINT rdkit_mol_version_meta_pkey PRIMARY KEY (singleton);


--
-- Name: reaction_rdkit_failures reaction_rdkit_failures_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.reaction_rdkit_failures
    ADD CONSTRAINT reaction_rdkit_failures_pkey PRIMARY KEY (reaction_id);


--
-- Name: reaction_rdkit_migration_meta reaction_rdkit_migration_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.reaction_rdkit_migration_meta
    ADD CONSTRAINT reaction_rdkit_migration_meta_pkey PRIMARY KEY (key);


--
-- Name: reactions_migration_meta reactions_migration_meta_pkey; Type: CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.reactions_migration_meta
    ADD CONSTRAINT reactions_migration_meta_pkey PRIMARY KEY (key);


--
-- Name: chemicalbook_seed chemicalbook_seed_pkey; Type: CONSTRAINT; Schema: ingestion; Owner: -
--

ALTER TABLE ONLY ingestion.chemicalbook_seed
    ADD CONSTRAINT chemicalbook_seed_pkey PRIMARY KEY (cb_number);


--
-- Name: cas_jobs cas_jobs_pkey; Type: CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.cas_jobs
    ADD CONSTRAINT cas_jobs_pkey PRIMARY KEY (id);


--
-- Name: cb_negative_observations cb_negative_observations_pkey; Type: CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.cb_negative_observations
    ADD CONSTRAINT cb_negative_observations_pkey PRIMARY KEY (negative_key);


--
-- Name: chemical_identity_redirect chemical_identity_redirect_pkey; Type: CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.chemical_identity_redirect
    ADD CONSTRAINT chemical_identity_redirect_pkey PRIMARY KEY (old_chemical_id);


--
-- Name: identity_merge_log identity_merge_log_pkey; Type: CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.identity_merge_log
    ADD CONSTRAINT identity_merge_log_pkey PRIMARY KEY (merge_id);


--
-- Name: pubchem_identity_jobs pubchem_identity_jobs_pkey; Type: CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.pubchem_identity_jobs
    ADD CONSTRAINT pubchem_identity_jobs_pkey PRIMARY KEY (id);


--
-- Name: pubchem_job_events pubchem_job_events_pkey; Type: CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.pubchem_job_events
    ADD CONSTRAINT pubchem_job_events_pkey PRIMARY KEY (id);


--
-- Name: pubchem_jobs pubchem_jobs_pkey; Type: CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.pubchem_jobs
    ADD CONSTRAINT pubchem_jobs_pkey PRIMARY KEY (id);


--
-- Name: worker_clients worker_clients_pkey; Type: CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.worker_clients
    ADD CONSTRAINT worker_clients_pkey PRIMARY KEY (worker_id);


--
-- Name: worker_clients worker_clients_token_hash_key; Type: CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.worker_clients
    ADD CONSTRAINT worker_clients_token_hash_key UNIQUE (token_hash);


--
-- Name: addition_device addition_device_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.addition_device
    ADD CONSTRAINT addition_device_pkey PRIMARY KEY (id);


--
-- Name: addition_speed addition_speed_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.addition_speed
    ADD CONSTRAINT addition_speed_pkey PRIMARY KEY (id);


--
-- Name: amount amount_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.amount
    ADD CONSTRAINT amount_pkey PRIMARY KEY (id);


--
-- Name: analysis analysis_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.analysis
    ADD CONSTRAINT analysis_pkey PRIMARY KEY (id);


--
-- Name: atmosphere atmosphere_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.atmosphere
    ADD CONSTRAINT atmosphere_pkey PRIMARY KEY (id);


--
-- Name: compound compound_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.compound
    ADD CONSTRAINT compound_pkey PRIMARY KEY (id);


--
-- Name: compound_preparation compound_preparation_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.compound_preparation
    ADD CONSTRAINT compound_preparation_pkey PRIMARY KEY (id);


--
-- Name: crude_component crude_component_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.crude_component
    ADD CONSTRAINT crude_component_pkey PRIMARY KEY (id);


--
-- Name: current current_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.current
    ADD CONSTRAINT current_pkey PRIMARY KEY (id);


--
-- Name: data data_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.data
    ADD CONSTRAINT data_pkey PRIMARY KEY (id);


--
-- Name: dataset dataset_dataset_id_key; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.dataset
    ADD CONSTRAINT dataset_dataset_id_key UNIQUE (dataset_id);


--
-- Name: dataset dataset_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.dataset
    ADD CONSTRAINT dataset_pkey PRIMARY KEY (id);


--
-- Name: date_time date_time_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.date_time
    ADD CONSTRAINT date_time_pkey PRIMARY KEY (id);


--
-- Name: electrochemistry_cell electrochemistry_cell_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.electrochemistry_cell
    ADD CONSTRAINT electrochemistry_cell_pkey PRIMARY KEY (id);


--
-- Name: electrochemistry_conditions electrochemistry_conditions_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.electrochemistry_conditions
    ADD CONSTRAINT electrochemistry_conditions_pkey PRIMARY KEY (id);


--
-- Name: electrochemistry_measurement electrochemistry_measurement_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.electrochemistry_measurement
    ADD CONSTRAINT electrochemistry_measurement_pkey PRIMARY KEY (id);


--
-- Name: float_value float_value_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.float_value
    ADD CONSTRAINT float_value_pkey PRIMARY KEY (id);


--
-- Name: flow_conditions flow_conditions_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.flow_conditions
    ADD CONSTRAINT flow_conditions_pkey PRIMARY KEY (id);


--
-- Name: flow_rate flow_rate_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.flow_rate
    ADD CONSTRAINT flow_rate_pkey PRIMARY KEY (id);


--
-- Name: illumination_conditions illumination_conditions_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.illumination_conditions
    ADD CONSTRAINT illumination_conditions_pkey PRIMARY KEY (id);


--
-- Name: reaction_map legacy_reaction_map_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_map
    ADD CONSTRAINT legacy_reaction_map_pkey PRIMARY KEY (ord_reaction_id);


--
-- Name: reaction_map legacy_reaction_map_reaction_id_key; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_map
    ADD CONSTRAINT legacy_reaction_map_reaction_id_key UNIQUE (reaction_id);


--
-- Name: length length_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.length
    ADD CONSTRAINT length_pkey PRIMARY KEY (id);


--
-- Name: mass mass_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.mass
    ADD CONSTRAINT mass_pkey PRIMARY KEY (id);


--
-- Name: mass_spec_measurement_details mass_spec_measurement_details_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.mass_spec_measurement_details
    ADD CONSTRAINT mass_spec_measurement_details_pkey PRIMARY KEY (id);


--
-- Name: moles moles_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.moles
    ADD CONSTRAINT moles_pkey PRIMARY KEY (id);


--
-- Name: percentage percentage_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.percentage
    ADD CONSTRAINT percentage_pkey PRIMARY KEY (id);


--
-- Name: person person_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.person
    ADD CONSTRAINT person_pkey PRIMARY KEY (id);


--
-- Name: pressure_conditions pressure_conditions_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure_conditions
    ADD CONSTRAINT pressure_conditions_pkey PRIMARY KEY (id);


--
-- Name: pressure_control pressure_control_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure_control
    ADD CONSTRAINT pressure_control_pkey PRIMARY KEY (id);


--
-- Name: pressure_measurement pressure_measurement_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure_measurement
    ADD CONSTRAINT pressure_measurement_pkey PRIMARY KEY (id);


--
-- Name: pressure pressure_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure
    ADD CONSTRAINT pressure_pkey PRIMARY KEY (id);


--
-- Name: product_compound product_compound_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.product_compound
    ADD CONSTRAINT product_compound_pkey PRIMARY KEY (id);


--
-- Name: product_measurement product_measurement_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.product_measurement
    ADD CONSTRAINT product_measurement_pkey PRIMARY KEY (id);


--
-- Name: reaction_conditions reaction_conditions_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_conditions
    ADD CONSTRAINT reaction_conditions_pkey PRIMARY KEY (id);


--
-- Name: reaction_environment reaction_environment_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_environment
    ADD CONSTRAINT reaction_environment_pkey PRIMARY KEY (id);


--
-- Name: reaction_identifier reaction_identifier_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_identifier
    ADD CONSTRAINT reaction_identifier_pkey PRIMARY KEY (id);


--
-- Name: reaction_input reaction_input_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_input
    ADD CONSTRAINT reaction_input_pkey PRIMARY KEY (id);


--
-- Name: reaction_notes reaction_notes_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_notes
    ADD CONSTRAINT reaction_notes_pkey PRIMARY KEY (id);


--
-- Name: reaction_observation reaction_observation_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_observation
    ADD CONSTRAINT reaction_observation_pkey PRIMARY KEY (id);


--
-- Name: reaction_outcome reaction_outcome_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_outcome
    ADD CONSTRAINT reaction_outcome_pkey PRIMARY KEY (id);


--
-- Name: reaction reaction_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction
    ADD CONSTRAINT reaction_pkey PRIMARY KEY (id);


--
-- Name: reaction_provenance reaction_provenance_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_provenance
    ADD CONSTRAINT reaction_provenance_pkey PRIMARY KEY (id);


--
-- Name: reaction reaction_reaction_id_key; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction
    ADD CONSTRAINT reaction_reaction_id_key UNIQUE (reaction_id);


--
-- Name: reaction_setup reaction_setup_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_setup
    ADD CONSTRAINT reaction_setup_pkey PRIMARY KEY (id);


--
-- Name: reaction_workup reaction_workup_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_workup
    ADD CONSTRAINT reaction_workup_pkey PRIMARY KEY (id);


--
-- Name: record_event record_event_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.record_event
    ADD CONSTRAINT record_event_pkey PRIMARY KEY (id);


--
-- Name: selectivity selectivity_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.selectivity
    ADD CONSTRAINT selectivity_pkey PRIMARY KEY (id);


--
-- Name: source source_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.source
    ADD CONSTRAINT source_pkey PRIMARY KEY (id);


--
-- Name: stirring_conditions stirring_conditions_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.stirring_conditions
    ADD CONSTRAINT stirring_conditions_pkey PRIMARY KEY (id);


--
-- Name: stirring_rate stirring_rate_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.stirring_rate
    ADD CONSTRAINT stirring_rate_pkey PRIMARY KEY (id);


--
-- Name: temperature_conditions temperature_conditions_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_conditions
    ADD CONSTRAINT temperature_conditions_pkey PRIMARY KEY (id);


--
-- Name: temperature_control temperature_control_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_control
    ADD CONSTRAINT temperature_control_pkey PRIMARY KEY (id);


--
-- Name: temperature_measurement temperature_measurement_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_measurement
    ADD CONSTRAINT temperature_measurement_pkey PRIMARY KEY (id);


--
-- Name: temperature temperature_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature
    ADD CONSTRAINT temperature_pkey PRIMARY KEY (id);


--
-- Name: texture texture_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.texture
    ADD CONSTRAINT texture_pkey PRIMARY KEY (id);


--
-- Name: time time_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time"
    ADD CONSTRAINT time_pkey PRIMARY KEY (id);


--
-- Name: tubing tubing_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.tubing
    ADD CONSTRAINT tubing_pkey PRIMARY KEY (id);


--
-- Name: unmeasured_amount unmeasured_amount_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.unmeasured_amount
    ADD CONSTRAINT unmeasured_amount_pkey PRIMARY KEY (id);


--
-- Name: vessel_attachment vessel_attachment_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel_attachment
    ADD CONSTRAINT vessel_attachment_pkey PRIMARY KEY (id);


--
-- Name: vessel_material vessel_material_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel_material
    ADD CONSTRAINT vessel_material_pkey PRIMARY KEY (id);


--
-- Name: vessel vessel_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel
    ADD CONSTRAINT vessel_pkey PRIMARY KEY (id);


--
-- Name: vessel_preparation vessel_preparation_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel_preparation
    ADD CONSTRAINT vessel_preparation_pkey PRIMARY KEY (id);


--
-- Name: voltage voltage_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.voltage
    ADD CONSTRAINT voltage_pkey PRIMARY KEY (id);


--
-- Name: volume volume_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.volume
    ADD CONSTRAINT volume_pkey PRIMARY KEY (id);


--
-- Name: wavelength wavelength_pkey; Type: CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.wavelength
    ADD CONSTRAINT wavelength_pkey PRIMARY KEY (id);


--
-- Name: chemical_cb_legacy_null_uidx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE UNIQUE INDEX chemical_cb_legacy_null_uidx ON chemistry.chemical_cb USING btree (chemical_id, locale) WHERE (cb_number IS NULL);


--
-- Name: chemical_cb_source_grain_uidx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE UNIQUE INDEX chemical_cb_source_grain_uidx ON chemistry.chemical_cb USING btree (chemical_id, cb_number, locale) WHERE (cb_number IS NOT NULL);


--
-- Name: chemical_supplier_listing_cbsid_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemical_supplier_listing_cbsid_idx ON chemistry.chemical_supplier_listing USING btree (cbsid);


--
-- Name: chemicals_cb_number_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_cb_number_idx ON chemistry.chemicals USING btree (cb_number) WHERE (cb_number IS NOT NULL);


--
-- Name: chemicals_dtxsid_uidx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE UNIQUE INDEX chemicals_dtxsid_uidx ON chemistry.chemicals USING btree (dtxsid) WHERE (dtxsid IS NOT NULL);


--
-- Name: chemicals_identifiers_gin; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_identifiers_gin ON chemistry.chemicals USING gin (cas_numbers, nikkaji_numbers, chembl_ids, ec_numbers, unii_codes, chebi_ids) WHERE ((cas_numbers IS NOT NULL) OR (nikkaji_numbers IS NOT NULL) OR (chembl_ids IS NOT NULL) OR (ec_numbers IS NOT NULL) OR (unii_codes IS NOT NULL) OR (chebi_ids IS NOT NULL));


--
-- Name: chemicals_inchikey_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_inchikey_idx ON chemistry.chemicals USING btree (inchikey) WHERE (inchikey IS NOT NULL);


--
-- Name: chemicals_iupac_name_trgm_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_iupac_name_trgm_idx ON chemistry.chemicals USING gin (iupac_name public.gin_trgm_ops) WHERE (iupac_name IS NOT NULL);


--
-- Name: chemicals_mol_gist_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_mol_gist_idx ON chemistry.chemicals USING gist (mol) WHERE (mol IS NOT NULL);


--
-- Name: chemicals_morgan_bfp_gist_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_morgan_bfp_gist_idx ON chemistry.chemicals USING gist (morgan_bfp) WHERE (mol IS NOT NULL);


--
-- Name: chemicals_morgan_sfp_gist_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_morgan_sfp_gist_idx ON chemistry.chemicals USING gist (morgan_sfp) WHERE (mol IS NOT NULL);


--
-- Name: chemicals_preferred_name_trgm_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_preferred_name_trgm_idx ON chemistry.chemicals USING gin (preferred_name public.gin_trgm_ops) WHERE (preferred_name IS NOT NULL);


--
-- Name: chemicals_pubchem_cid_brin; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_pubchem_cid_brin ON chemistry.chemicals USING brin (pubchem_cid) WITH (pages_per_range='32') WHERE (pubchem_cid IS NOT NULL);


--
-- Name: chemicals_pubchem_cid_btree_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_pubchem_cid_btree_idx ON chemistry.chemicals USING btree (pubchem_cid) WHERE (pubchem_cid IS NOT NULL);


--
-- Name: chemicals_rdkit_smiles_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX chemicals_rdkit_smiles_idx ON chemistry.chemicals USING btree (smiles) WHERE (mol IS NOT NULL);


--
-- Name: name_index_chemical_id_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX name_index_chemical_id_idx ON chemistry.name_index USING btree (chemical_id);


--
-- Name: name_index_normalized_trgm_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX name_index_normalized_trgm_idx ON chemistry.name_index USING gin (normalized public.gin_trgm_ops);


--
-- Name: reaction_chemicals_chemical_reaction_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX reaction_chemicals_chemical_reaction_idx ON chemistry.reaction_chemicals USING btree (chemical_id, reaction_id);


--
-- Name: reactions_doi_lower_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX reactions_doi_lower_idx ON chemistry.reactions USING btree (lower(doi), id) WHERE (doi IS NOT NULL);


--
-- Name: reactions_excluded_from_public_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX reactions_excluded_from_public_idx ON chemistry.reactions USING btree (id) WHERE ((visibility <> 'public'::text) OR (moderation_status <> 'visible'::text));


--
-- Name: reactions_owner_idempotency_uidx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE UNIQUE INDEX reactions_owner_idempotency_uidx ON chemistry.reactions USING btree (created_by_user_id, idempotency_key) WHERE ((created_by_user_id IS NOT NULL) AND (idempotency_key IS NOT NULL));


--
-- Name: reactions_owner_visibility_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX reactions_owner_visibility_idx ON chemistry.reactions USING btree (created_by_user_id, visibility, id DESC) WHERE (created_by_user_id IS NOT NULL);


--
-- Name: reactions_reaction_gist_idx; Type: INDEX; Schema: chemistry; Owner: -
--

CREATE INDEX reactions_reaction_gist_idx ON chemistry.reactions USING gist (reaction) WHERE (reaction IS NOT NULL);


--
-- Name: chemical_follows_chemical_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX chemical_follows_chemical_idx ON community.chemical_follows USING btree (chemical_id, user_id);


--
-- Name: chemical_follows_user_created_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX chemical_follows_user_created_idx ON community.chemical_follows USING btree (user_id, created_at DESC, chemical_id);


--
-- Name: community_sessions_expiry_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX community_sessions_expiry_idx ON community.sessions USING btree (expires_at);


--
-- Name: community_sessions_user_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX community_sessions_user_idx ON community.sessions USING btree (user_id);


--
-- Name: community_users_email_uidx; Type: INDEX; Schema: community; Owner: -
--

CREATE UNIQUE INDEX community_users_email_uidx ON community.users USING btree (lower(email));


--
-- Name: community_users_username_uidx; Type: INDEX; Schema: community; Owner: -
--

CREATE UNIQUE INDEX community_users_username_uidx ON community.users USING btree (lower(username));


--
-- Name: notifications_activity_feed_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX notifications_activity_feed_idx ON community.notifications USING btree (user_id, created_at DESC, id DESC) WHERE (event_type = 'new_reaction'::text);


--
-- Name: notifications_user_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX notifications_user_idx ON community.notifications USING btree (user_id, read_at, created_at DESC);


--
-- Name: reaction_follows_reaction_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX reaction_follows_reaction_idx ON community.reaction_follows USING btree (reaction_id, user_id);


--
-- Name: reaction_follows_user_created_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX reaction_follows_user_created_idx ON community.reaction_follows USING btree (user_id, created_at DESC, reaction_id);


--
-- Name: skill_files_skill_path_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE UNIQUE INDEX skill_files_skill_path_idx ON community.skill_files USING btree (skill_id, path);


--
-- Name: skills_admin_list_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX skills_admin_list_idx ON community.skills USING btree (visibility, updated_at DESC);


--
-- Name: skills_owner_slug_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE UNIQUE INDEX skills_owner_slug_idx ON community.skills USING btree (owner_id, slug);


--
-- Name: skills_owner_updated_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX skills_owner_updated_idx ON community.skills USING btree (owner_id, updated_at DESC);


--
-- Name: skills_public_list_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX skills_public_list_idx ON community.skills USING btree (category, updated_at DESC) WHERE (visibility = 'public'::text);


--
-- Name: user_api_tokens_user_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX user_api_tokens_user_idx ON community.user_api_tokens USING btree (user_id, created_at DESC);


--
-- Name: user_follows_followed_created_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX user_follows_followed_created_idx ON community.user_follows USING btree (followed_user_id, created_at DESC, follower_user_id);


--
-- Name: user_follows_follower_created_idx; Type: INDEX; Schema: community; Owner: -
--

CREATE INDEX user_follows_follower_created_idx ON community.user_follows USING btree (follower_user_id, created_at DESC, followed_user_id);


--
-- Name: dsstox_chemical_matches_pubchem_cid_idx; Type: INDEX; Schema: ingest; Owner: -
--

CREATE INDEX dsstox_chemical_matches_pubchem_cid_idx ON ingest.dsstox_chemical_matches USING btree (pubchem_cid);


--
-- Name: dsstox_residual_cas_cid_idx; Type: INDEX; Schema: ingest; Owner: -
--

CREATE INDEX dsstox_residual_cas_cid_idx ON ingest.dsstox_residual_cas_classification USING btree (pubchem_cid);


--
-- Name: dsstox_residual_exact_cid_idx; Type: INDEX; Schema: ingest; Owner: -
--

CREATE INDEX dsstox_residual_exact_cid_idx ON ingest.dsstox_residual_exact_candidates USING btree (pubchem_cid);


--
-- Name: dsstox_residual_exact_source_idx; Type: INDEX; Schema: ingest; Owner: -
--

CREATE INDEX dsstox_residual_exact_source_idx ON ingest.dsstox_residual_exact_candidates USING btree (source_row);


--
-- Name: rdkit_mol_chemical_map_chemical_idx; Type: INDEX; Schema: ingest; Owner: -
--

CREATE INDEX rdkit_mol_chemical_map_chemical_idx ON ingest.rdkit_mol_chemical_map USING btree (chemical_id);


--
-- Name: chemicalbook_seed_cas_idx; Type: INDEX; Schema: ingestion; Owner: -
--

CREATE INDEX chemicalbook_seed_cas_idx ON ingestion.chemicalbook_seed USING btree (cas);


--
-- Name: chemicalbook_seed_status_cb_idx; Type: INDEX; Schema: ingestion; Owner: -
--

CREATE INDEX chemicalbook_seed_status_cb_idx ON ingestion.chemicalbook_seed USING btree (status, cb_number);


--
-- Name: cas_jobs_active_dedupe_uidx; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE UNIQUE INDEX cas_jobs_active_dedupe_uidx ON maintenance.cas_jobs USING btree (dedupe_key) WHERE (status = ANY (ARRAY['queued'::text, 'leased'::text, 'error'::text]));


--
-- Name: cas_jobs_claim_idx; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE INDEX cas_jobs_claim_idx ON maintenance.cas_jobs USING btree (priority DESC, id) WHERE (status = 'queued'::text);


--
-- Name: cas_jobs_lease_expiry_idx; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE INDEX cas_jobs_lease_expiry_idx ON maintenance.cas_jobs USING btree (lease_expires_at, id) WHERE (status = 'leased'::text);


--
-- Name: ix_identity_merge_log_source; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE INDEX ix_identity_merge_log_source ON maintenance.identity_merge_log USING btree (source_id);


--
-- Name: ix_identity_merge_log_target; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE INDEX ix_identity_merge_log_target ON maintenance.identity_merge_log USING btree (target_id);


--
-- Name: pubchem_identity_jobs_chem_idx; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE INDEX pubchem_identity_jobs_chem_idx ON maintenance.pubchem_identity_jobs USING btree (chemical_id);


--
-- Name: pubchem_identity_jobs_claim_idx; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE INDEX pubchem_identity_jobs_claim_idx ON maintenance.pubchem_identity_jobs USING btree (status, priority, id) WHERE (status = 'queued'::text);


--
-- Name: pubchem_identity_jobs_dedupe_idx; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE UNIQUE INDEX pubchem_identity_jobs_dedupe_idx ON maintenance.pubchem_identity_jobs USING btree (dedupe_key);


--
-- Name: pubchem_job_events_job_idx; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE INDEX pubchem_job_events_job_idx ON maintenance.pubchem_job_events USING btree (job_id, created_at);


--
-- Name: pubchem_jobs_active_dedupe_uidx; Type: INDEX; Schema: maintenance; Owner: -
--

CREATE UNIQUE INDEX pubchem_jobs_active_dedupe_uidx ON maintenance.pubchem_jobs USING btree (dedupe_key) WHERE (status = ANY (ARRAY['queued'::text, 'leased'::text, 'error'::text]));


--
-- Name: ix_ord_addition_device_reaction_input_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_addition_device_reaction_input_id ON ord.addition_device USING btree (reaction_input_id);


--
-- Name: ix_ord_addition_speed_reaction_input_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_addition_speed_reaction_input_id ON ord.addition_speed USING btree (reaction_input_id);


--
-- Name: ix_ord_amount_crude_component_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_amount_crude_component_id ON ord.amount USING btree (crude_component_id);


--
-- Name: ix_ord_amount_product_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_amount_product_measurement_id ON ord.amount USING btree (product_measurement_id);


--
-- Name: ix_ord_amount_reaction_workup_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_amount_reaction_workup_id ON ord.amount USING btree (reaction_workup_id);


--
-- Name: ix_ord_analysis_compound_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_analysis_compound_id ON ord.analysis USING btree (compound_id);


--
-- Name: ix_ord_analysis_reaction_outcome_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_analysis_reaction_outcome_id ON ord.analysis USING btree (reaction_outcome_id);


--
-- Name: ix_ord_atmosphere_pressure_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_atmosphere_pressure_conditions_id ON ord.atmosphere USING btree (pressure_conditions_id);


--
-- Name: ix_ord_compound_chemical_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_compound_chemical_id ON ord.compound USING btree (chemical_id);


--
-- Name: ix_ord_compound_preparation_compound_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_compound_preparation_compound_id ON ord.compound_preparation USING btree (compound_id);


--
-- Name: ix_ord_compound_preparation_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_compound_preparation_reaction_id ON ord.compound_preparation USING btree (reaction_id);


--
-- Name: ix_ord_compound_product_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_compound_product_measurement_id ON ord.compound USING btree (product_measurement_id);


--
-- Name: ix_ord_crude_component_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_crude_component_reaction_id ON ord.crude_component USING btree (reaction_id);


--
-- Name: ix_ord_crude_component_reaction_input_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_crude_component_reaction_input_id ON ord.crude_component USING btree (reaction_input_id);


--
-- Name: ix_ord_current_electrochemistry_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_current_electrochemistry_conditions_id ON ord.current USING btree (electrochemistry_conditions_id);


--
-- Name: ix_ord_current_electrochemistry_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_current_electrochemistry_measurement_id ON ord.current USING btree (electrochemistry_measurement_id);


--
-- Name: ix_ord_data_analysis_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_data_analysis_id ON ord.data USING btree (analysis_id);


--
-- Name: ix_ord_data_compound_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_data_compound_id ON ord.data USING btree (compound_id);


--
-- Name: ix_ord_data_product_compound_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_data_product_compound_id ON ord.data USING btree (product_compound_id);


--
-- Name: ix_ord_data_reaction_observation_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_data_reaction_observation_id ON ord.data USING btree (reaction_observation_id);


--
-- Name: ix_ord_data_reaction_provenance_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_data_reaction_provenance_id ON ord.data USING btree (reaction_provenance_id);


--
-- Name: ix_ord_data_reaction_setup_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_data_reaction_setup_id ON ord.data USING btree (reaction_setup_id);


--
-- Name: ix_ord_dataset_submitted_at; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_dataset_submitted_at ON ord.dataset USING btree (submitted_at);


--
-- Name: ix_ord_date_time_analysis_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_date_time_analysis_id ON ord.date_time USING btree (analysis_id);


--
-- Name: ix_ord_date_time_reaction_provenance_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_date_time_reaction_provenance_id ON ord.date_time USING btree (reaction_provenance_id);


--
-- Name: ix_ord_electrochemistry_cell_electrochemistry_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_electrochemistry_cell_electrochemistry_conditions_id ON ord.electrochemistry_cell USING btree (electrochemistry_conditions_id);


--
-- Name: ix_ord_electrochemistry_conditions_reaction_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_electrochemistry_conditions_reaction_conditions_id ON ord.electrochemistry_conditions USING btree (reaction_conditions_id);


--
-- Name: ix_ord_electrochemistry_measurement_electrochemistry_co_7ab0; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_electrochemistry_measurement_electrochemistry_co_7ab0 ON ord.electrochemistry_measurement USING btree (electrochemistry_conditions_id);


--
-- Name: ix_ord_float_value_product_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_float_value_product_measurement_id ON ord.float_value USING btree (product_measurement_id);


--
-- Name: ix_ord_flow_conditions_reaction_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_flow_conditions_reaction_conditions_id ON ord.flow_conditions USING btree (reaction_conditions_id);


--
-- Name: ix_ord_flow_rate_reaction_input_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_flow_rate_reaction_input_id ON ord.flow_rate USING btree (reaction_input_id);


--
-- Name: ix_ord_illumination_conditions_reaction_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_illumination_conditions_reaction_conditions_id ON ord.illumination_conditions USING btree (reaction_conditions_id);


--
-- Name: ix_ord_length_electrochemistry_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_length_electrochemistry_conditions_id ON ord.length USING btree (electrochemistry_conditions_id);


--
-- Name: ix_ord_length_illumination_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_length_illumination_conditions_id ON ord.length USING btree (illumination_conditions_id);


--
-- Name: ix_ord_length_tubing_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_length_tubing_id ON ord.length USING btree (tubing_id);


--
-- Name: ix_ord_mass_amount_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_mass_amount_id ON ord.mass USING btree (amount_id);


--
-- Name: ix_ord_mass_spec_measurement_details_product_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_mass_spec_measurement_details_product_measurement_id ON ord.mass_spec_measurement_details USING btree (product_measurement_id);


--
-- Name: ix_ord_moles_amount_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_moles_amount_id ON ord.moles USING btree (amount_id);


--
-- Name: ix_ord_percentage_product_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_percentage_product_measurement_id ON ord.percentage USING btree (product_measurement_id);


--
-- Name: ix_ord_percentage_reaction_outcome_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_percentage_reaction_outcome_id ON ord.percentage USING btree (reaction_outcome_id);


--
-- Name: ix_ord_person_reaction_provenance_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_person_reaction_provenance_id ON ord.person USING btree (reaction_provenance_id);


--
-- Name: ix_ord_pressure_conditions_reaction_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_pressure_conditions_reaction_conditions_id ON ord.pressure_conditions USING btree (reaction_conditions_id);


--
-- Name: ix_ord_pressure_control_pressure_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_pressure_control_pressure_conditions_id ON ord.pressure_control USING btree (pressure_conditions_id);


--
-- Name: ix_ord_pressure_measurement_pressure_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_pressure_measurement_pressure_conditions_id ON ord.pressure_measurement USING btree (pressure_conditions_id);


--
-- Name: ix_ord_pressure_pressure_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_pressure_pressure_conditions_id ON ord.pressure USING btree (pressure_conditions_id);


--
-- Name: ix_ord_pressure_pressure_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_pressure_pressure_measurement_id ON ord.pressure USING btree (pressure_measurement_id);


--
-- Name: ix_ord_product_compound_chemical_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_product_compound_chemical_id ON ord.product_compound USING btree (chemical_id);


--
-- Name: ix_ord_product_compound_reaction_outcome_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_product_compound_reaction_outcome_id ON ord.product_compound USING btree (reaction_outcome_id);


--
-- Name: ix_ord_product_measurement_product_compound_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_product_measurement_product_compound_id ON ord.product_measurement USING btree (product_compound_id);


--
-- Name: ix_ord_reaction_conditions_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_conditions_reaction_id ON ord.reaction_conditions USING btree (reaction_id);


--
-- Name: ix_ord_reaction_dataset_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_dataset_id ON ord.reaction USING btree (dataset_id);


--
-- Name: ix_ord_reaction_environment_reaction_setup_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_environment_reaction_setup_id ON ord.reaction_environment USING btree (reaction_setup_id);


--
-- Name: ix_ord_reaction_identifier_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_identifier_reaction_id ON ord.reaction_identifier USING btree (reaction_id);


--
-- Name: ix_ord_reaction_input_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_input_reaction_id ON ord.reaction_input USING btree (reaction_id);


--
-- Name: ix_ord_reaction_input_reaction_workup_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_input_reaction_workup_id ON ord.reaction_input USING btree (reaction_workup_id);


--
-- Name: ix_ord_reaction_notes_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_notes_reaction_id ON ord.reaction_notes USING btree (reaction_id);


--
-- Name: ix_ord_reaction_observation_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_observation_reaction_id ON ord.reaction_observation USING btree (reaction_id);


--
-- Name: ix_ord_reaction_outcome_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_outcome_reaction_id ON ord.reaction_outcome USING btree (reaction_id);


--
-- Name: ix_ord_reaction_provenance_doi; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_provenance_doi ON ord.reaction_provenance USING btree (doi);


--
-- Name: ix_ord_reaction_provenance_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_provenance_reaction_id ON ord.reaction_provenance USING btree (reaction_id);


--
-- Name: ix_ord_reaction_setup_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_setup_reaction_id ON ord.reaction_setup USING btree (reaction_id);


--
-- Name: ix_ord_reaction_workup_reaction_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_reaction_workup_reaction_id ON ord.reaction_workup USING btree (reaction_id);


--
-- Name: ix_ord_record_event_reaction_provenance_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_record_event_reaction_provenance_id ON ord.record_event USING btree (reaction_provenance_id);


--
-- Name: ix_ord_selectivity_product_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_selectivity_product_measurement_id ON ord.selectivity USING btree (product_measurement_id);


--
-- Name: ix_ord_source_compound_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_source_compound_id ON ord.source USING btree (compound_id);


--
-- Name: ix_ord_stirring_conditions_reaction_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_stirring_conditions_reaction_conditions_id ON ord.stirring_conditions USING btree (reaction_conditions_id);


--
-- Name: ix_ord_stirring_conditions_reaction_workup_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_stirring_conditions_reaction_workup_id ON ord.stirring_conditions USING btree (reaction_workup_id);


--
-- Name: ix_ord_stirring_rate_stirring_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_stirring_rate_stirring_conditions_id ON ord.stirring_rate USING btree (stirring_conditions_id);


--
-- Name: ix_ord_temperature_conditions_reaction_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_temperature_conditions_reaction_conditions_id ON ord.temperature_conditions USING btree (reaction_conditions_id);


--
-- Name: ix_ord_temperature_conditions_reaction_workup_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_temperature_conditions_reaction_workup_id ON ord.temperature_conditions USING btree (reaction_workup_id);


--
-- Name: ix_ord_temperature_control_temperature_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_temperature_control_temperature_conditions_id ON ord.temperature_control USING btree (temperature_conditions_id);


--
-- Name: ix_ord_temperature_measurement_temperature_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_temperature_measurement_temperature_conditions_id ON ord.temperature_measurement USING btree (temperature_conditions_id);


--
-- Name: ix_ord_temperature_reaction_input_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_temperature_reaction_input_id ON ord.temperature USING btree (reaction_input_id);


--
-- Name: ix_ord_temperature_temperature_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_temperature_temperature_conditions_id ON ord.temperature USING btree (temperature_conditions_id);


--
-- Name: ix_ord_temperature_temperature_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_temperature_temperature_measurement_id ON ord.temperature USING btree (temperature_measurement_id);


--
-- Name: ix_ord_texture_compound_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_texture_compound_id ON ord.texture USING btree (compound_id);


--
-- Name: ix_ord_texture_crude_component_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_texture_crude_component_id ON ord.texture USING btree (crude_component_id);


--
-- Name: ix_ord_texture_product_compound_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_texture_product_compound_id ON ord.texture USING btree (product_compound_id);


--
-- Name: ix_ord_texture_reaction_input_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_texture_reaction_input_id ON ord.texture USING btree (reaction_input_id);


--
-- Name: ix_ord_time_electrochemistry_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_time_electrochemistry_measurement_id ON ord."time" USING btree (electrochemistry_measurement_id);


--
-- Name: ix_ord_time_pressure_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_time_pressure_measurement_id ON ord."time" USING btree (pressure_measurement_id);


--
-- Name: ix_ord_time_product_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_time_product_measurement_id ON ord."time" USING btree (product_measurement_id);


--
-- Name: ix_ord_time_reaction_input_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_time_reaction_input_id ON ord."time" USING btree (reaction_input_id);


--
-- Name: ix_ord_time_reaction_observation_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_time_reaction_observation_id ON ord."time" USING btree (reaction_observation_id);


--
-- Name: ix_ord_time_reaction_outcome_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_time_reaction_outcome_id ON ord."time" USING btree (reaction_outcome_id);


--
-- Name: ix_ord_time_reaction_workup_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_time_reaction_workup_id ON ord."time" USING btree (reaction_workup_id);


--
-- Name: ix_ord_time_temperature_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_time_temperature_measurement_id ON ord."time" USING btree (temperature_measurement_id);


--
-- Name: ix_ord_tubing_flow_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_tubing_flow_conditions_id ON ord.tubing USING btree (flow_conditions_id);


--
-- Name: ix_ord_unmeasured_amount_amount_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_unmeasured_amount_amount_id ON ord.unmeasured_amount USING btree (amount_id);


--
-- Name: ix_ord_vessel_attachment_vessel_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_vessel_attachment_vessel_id ON ord.vessel_attachment USING btree (vessel_id);


--
-- Name: ix_ord_vessel_material_vessel_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_vessel_material_vessel_id ON ord.vessel_material USING btree (vessel_id);


--
-- Name: ix_ord_vessel_preparation_vessel_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_vessel_preparation_vessel_id ON ord.vessel_preparation USING btree (vessel_id);


--
-- Name: ix_ord_vessel_reaction_setup_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_vessel_reaction_setup_id ON ord.vessel USING btree (reaction_setup_id);


--
-- Name: ix_ord_voltage_electrochemistry_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_voltage_electrochemistry_conditions_id ON ord.voltage USING btree (electrochemistry_conditions_id);


--
-- Name: ix_ord_voltage_electrochemistry_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_voltage_electrochemistry_measurement_id ON ord.voltage USING btree (electrochemistry_measurement_id);


--
-- Name: ix_ord_volume_amount_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_volume_amount_id ON ord.volume USING btree (amount_id);


--
-- Name: ix_ord_volume_vessel_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_volume_vessel_id ON ord.volume USING btree (vessel_id);


--
-- Name: ix_ord_wavelength_illumination_conditions_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_wavelength_illumination_conditions_id ON ord.wavelength USING btree (illumination_conditions_id);


--
-- Name: ix_ord_wavelength_product_measurement_id; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX ix_ord_wavelength_product_measurement_id ON ord.wavelength USING btree (product_measurement_id);


--
-- Name: product_compound_unlinked_index; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX product_compound_unlinked_index ON ord.product_compound USING btree (reaction_outcome_id) WHERE (chemical_id IS NULL);


--
-- Name: reaction_provenance_doi_lower_idx; Type: INDEX; Schema: ord; Owner: -
--

CREATE INDEX reaction_provenance_doi_lower_idx ON ord.reaction_provenance USING btree (lower(doi), reaction_id, id) WHERE (doi IS NOT NULL);


--
-- Name: chemical_cb cas_externals_chemical_id_fkey; Type: FK CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemical_cb
    ADD CONSTRAINT cas_externals_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE CASCADE;


--
-- Name: chemical_pubchem chemical_details_chemical_id_fkey; Type: FK CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemical_pubchem
    ADD CONSTRAINT chemical_details_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE CASCADE;


--
-- Name: chemical_supplier_listing chemical_supplier_listing_cbsid_fkey; Type: FK CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemical_supplier_listing
    ADD CONSTRAINT chemical_supplier_listing_cbsid_fkey FOREIGN KEY (cbsid) REFERENCES chemistry.chemical_supplier_profile(cbsid) ON DELETE CASCADE;


--
-- Name: chemical_supplier_listing chemical_supplier_listing_chemical_id_fkey; Type: FK CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.chemical_supplier_listing
    ADD CONSTRAINT chemical_supplier_listing_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE CASCADE;


--
-- Name: name_index name_index_chemical_id_fkey; Type: FK CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.name_index
    ADD CONSTRAINT name_index_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE CASCADE;


--
-- Name: reaction_chemicals reaction_chemicals_chemical_fkey; Type: FK CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.reaction_chemicals
    ADD CONSTRAINT reaction_chemicals_chemical_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE RESTRICT;


--
-- Name: reaction_chemicals reaction_chemicals_reaction_fkey; Type: FK CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.reaction_chemicals
    ADD CONSTRAINT reaction_chemicals_reaction_fkey FOREIGN KEY (reaction_id) REFERENCES chemistry.reactions(id) ON DELETE CASCADE;


--
-- Name: reactions reactions_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: chemistry; Owner: -
--

ALTER TABLE ONLY chemistry.reactions
    ADD CONSTRAINT reactions_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES community.users(id) ON DELETE RESTRICT;


--
-- Name: chemical_follows chemical_follows_chemical_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.chemical_follows
    ADD CONSTRAINT chemical_follows_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE CASCADE;


--
-- Name: chemical_follows chemical_follows_user_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.chemical_follows
    ADD CONSTRAINT chemical_follows_user_id_fkey FOREIGN KEY (user_id) REFERENCES community.users(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.notifications
    ADD CONSTRAINT notifications_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES community.users(id) ON DELETE SET NULL;


--
-- Name: notifications notifications_chemical_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.notifications
    ADD CONSTRAINT notifications_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_reaction_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.notifications
    ADD CONSTRAINT notifications_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES chemistry.reactions(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES community.users(id) ON DELETE CASCADE;


--
-- Name: reaction_follows reaction_follows_reaction_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.reaction_follows
    ADD CONSTRAINT reaction_follows_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES chemistry.reactions(id) ON DELETE CASCADE;


--
-- Name: reaction_follows reaction_follows_user_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.reaction_follows
    ADD CONSTRAINT reaction_follows_user_id_fkey FOREIGN KEY (user_id) REFERENCES community.users(id) ON DELETE CASCADE;


--
-- Name: sessions sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES community.users(id) ON DELETE CASCADE;


--
-- Name: skill_files skill_files_skill_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.skill_files
    ADD CONSTRAINT skill_files_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES community.skills(id) ON DELETE CASCADE;


--
-- Name: skills skills_owner_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.skills
    ADD CONSTRAINT skills_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES community.users(id) ON DELETE CASCADE;


--
-- Name: skills skills_published_by_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.skills
    ADD CONSTRAINT skills_published_by_fkey FOREIGN KEY (published_by) REFERENCES community.users(id);


--
-- Name: user_api_tokens user_api_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.user_api_tokens
    ADD CONSTRAINT user_api_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES community.users(id) ON DELETE CASCADE;


--
-- Name: user_follows user_follows_followed_user_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.user_follows
    ADD CONSTRAINT user_follows_followed_user_id_fkey FOREIGN KEY (followed_user_id) REFERENCES community.users(id) ON DELETE CASCADE;


--
-- Name: user_follows user_follows_follower_user_id_fkey; Type: FK CONSTRAINT; Schema: community; Owner: -
--

ALTER TABLE ONLY community.user_follows
    ADD CONSTRAINT user_follows_follower_user_id_fkey FOREIGN KEY (follower_user_id) REFERENCES community.users(id) ON DELETE CASCADE;


--
-- Name: reaction_rdkit_failures reaction_rdkit_failures_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ingest; Owner: -
--

ALTER TABLE ONLY ingest.reaction_rdkit_failures
    ADD CONSTRAINT reaction_rdkit_failures_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES chemistry.reactions(id) ON DELETE CASCADE;


--
-- Name: cas_jobs cas_jobs_chemical_id_fkey; Type: FK CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.cas_jobs
    ADD CONSTRAINT cas_jobs_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE SET NULL;


--
-- Name: chemical_identity_redirect chemical_identity_redirect_merge_log_id_fkey; Type: FK CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.chemical_identity_redirect
    ADD CONSTRAINT chemical_identity_redirect_merge_log_id_fkey FOREIGN KEY (merge_log_id) REFERENCES maintenance.identity_merge_log(merge_id);


--
-- Name: pubchem_job_events pubchem_job_events_job_id_fkey; Type: FK CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.pubchem_job_events
    ADD CONSTRAINT pubchem_job_events_job_id_fkey FOREIGN KEY (job_id) REFERENCES maintenance.pubchem_jobs(id) ON DELETE CASCADE;


--
-- Name: pubchem_job_events pubchem_job_events_worker_id_fkey; Type: FK CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.pubchem_job_events
    ADD CONSTRAINT pubchem_job_events_worker_id_fkey FOREIGN KEY (worker_id) REFERENCES maintenance.worker_clients(worker_id) ON DELETE SET NULL;


--
-- Name: pubchem_jobs pubchem_jobs_chemical_id_fkey; Type: FK CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.pubchem_jobs
    ADD CONSTRAINT pubchem_jobs_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE CASCADE;


--
-- Name: pubchem_jobs pubchem_jobs_lease_owner_fkey; Type: FK CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.pubchem_jobs
    ADD CONSTRAINT pubchem_jobs_lease_owner_fkey FOREIGN KEY (lease_owner) REFERENCES maintenance.worker_clients(worker_id) ON DELETE SET NULL;


--
-- Name: pubchem_jobs pubchem_jobs_requested_by_user_id_fkey; Type: FK CONSTRAINT; Schema: maintenance; Owner: -
--

ALTER TABLE ONLY maintenance.pubchem_jobs
    ADD CONSTRAINT pubchem_jobs_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES community.users(id) ON DELETE SET NULL;


--
-- Name: addition_device addition_device_reaction_input_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.addition_device
    ADD CONSTRAINT addition_device_reaction_input_id_fkey FOREIGN KEY (reaction_input_id) REFERENCES ord.reaction_input(id) ON DELETE CASCADE;


--
-- Name: addition_speed addition_speed_reaction_input_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.addition_speed
    ADD CONSTRAINT addition_speed_reaction_input_id_fkey FOREIGN KEY (reaction_input_id) REFERENCES ord.reaction_input(id) ON DELETE CASCADE;


--
-- Name: amount amount_compound_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.amount
    ADD CONSTRAINT amount_compound_id_fkey FOREIGN KEY (compound_id) REFERENCES ord.compound(id) ON DELETE CASCADE;


--
-- Name: amount amount_crude_component_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.amount
    ADD CONSTRAINT amount_crude_component_id_fkey FOREIGN KEY (crude_component_id) REFERENCES ord.crude_component(id) ON DELETE CASCADE;


--
-- Name: amount amount_product_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.amount
    ADD CONSTRAINT amount_product_measurement_id_fkey FOREIGN KEY (product_measurement_id) REFERENCES ord.product_measurement(id) ON DELETE CASCADE;


--
-- Name: amount amount_reaction_workup_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.amount
    ADD CONSTRAINT amount_reaction_workup_id_fkey FOREIGN KEY (reaction_workup_id) REFERENCES ord.reaction_workup(id) ON DELETE CASCADE;


--
-- Name: analysis analysis_compound_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.analysis
    ADD CONSTRAINT analysis_compound_id_fkey FOREIGN KEY (compound_id) REFERENCES ord.compound(id) ON DELETE CASCADE;


--
-- Name: analysis analysis_reaction_outcome_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.analysis
    ADD CONSTRAINT analysis_reaction_outcome_id_fkey FOREIGN KEY (reaction_outcome_id) REFERENCES ord.reaction_outcome(id) ON DELETE CASCADE;


--
-- Name: atmosphere atmosphere_pressure_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.atmosphere
    ADD CONSTRAINT atmosphere_pressure_conditions_id_fkey FOREIGN KEY (pressure_conditions_id) REFERENCES ord.pressure_conditions(id) ON DELETE CASCADE;


--
-- Name: compound compound_chemical_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.compound
    ADD CONSTRAINT compound_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE RESTRICT;


--
-- Name: compound_preparation compound_preparation_compound_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.compound_preparation
    ADD CONSTRAINT compound_preparation_compound_id_fkey FOREIGN KEY (compound_id) REFERENCES ord.compound(id) ON DELETE CASCADE;


--
-- Name: compound_preparation compound_preparation_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.compound_preparation
    ADD CONSTRAINT compound_preparation_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(reaction_id) ON DELETE CASCADE;


--
-- Name: compound compound_product_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.compound
    ADD CONSTRAINT compound_product_measurement_id_fkey FOREIGN KEY (product_measurement_id) REFERENCES ord.product_measurement(id) ON DELETE CASCADE;


--
-- Name: compound compound_reaction_input_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.compound
    ADD CONSTRAINT compound_reaction_input_id_fkey FOREIGN KEY (reaction_input_id) REFERENCES ord.reaction_input(id) ON DELETE CASCADE;


--
-- Name: crude_component crude_component_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.crude_component
    ADD CONSTRAINT crude_component_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(reaction_id) ON DELETE CASCADE;


--
-- Name: crude_component crude_component_reaction_input_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.crude_component
    ADD CONSTRAINT crude_component_reaction_input_id_fkey FOREIGN KEY (reaction_input_id) REFERENCES ord.reaction_input(id) ON DELETE CASCADE;


--
-- Name: current current_electrochemistry_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.current
    ADD CONSTRAINT current_electrochemistry_conditions_id_fkey FOREIGN KEY (electrochemistry_conditions_id) REFERENCES ord.electrochemistry_conditions(id) ON DELETE CASCADE;


--
-- Name: current current_electrochemistry_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.current
    ADD CONSTRAINT current_electrochemistry_measurement_id_fkey FOREIGN KEY (electrochemistry_measurement_id) REFERENCES ord.electrochemistry_measurement(id) ON DELETE CASCADE;


--
-- Name: data data_analysis_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.data
    ADD CONSTRAINT data_analysis_id_fkey FOREIGN KEY (analysis_id) REFERENCES ord.analysis(id) ON DELETE CASCADE;


--
-- Name: data data_compound_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.data
    ADD CONSTRAINT data_compound_id_fkey FOREIGN KEY (compound_id) REFERENCES ord.compound(id) ON DELETE CASCADE;


--
-- Name: data data_product_compound_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.data
    ADD CONSTRAINT data_product_compound_id_fkey FOREIGN KEY (product_compound_id) REFERENCES ord.product_compound(id) ON DELETE CASCADE;


--
-- Name: data data_reaction_observation_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.data
    ADD CONSTRAINT data_reaction_observation_id_fkey FOREIGN KEY (reaction_observation_id) REFERENCES ord.reaction_observation(id) ON DELETE CASCADE;


--
-- Name: data data_reaction_provenance_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.data
    ADD CONSTRAINT data_reaction_provenance_id_fkey FOREIGN KEY (reaction_provenance_id) REFERENCES ord.reaction_provenance(id) ON DELETE CASCADE;


--
-- Name: data data_reaction_setup_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.data
    ADD CONSTRAINT data_reaction_setup_id_fkey FOREIGN KEY (reaction_setup_id) REFERENCES ord.reaction_setup(id) ON DELETE CASCADE;


--
-- Name: date_time date_time_analysis_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.date_time
    ADD CONSTRAINT date_time_analysis_id_fkey FOREIGN KEY (analysis_id) REFERENCES ord.analysis(id) ON DELETE CASCADE;


--
-- Name: date_time date_time_reaction_provenance_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.date_time
    ADD CONSTRAINT date_time_reaction_provenance_id_fkey FOREIGN KEY (reaction_provenance_id) REFERENCES ord.reaction_provenance(id) ON DELETE CASCADE;


--
-- Name: date_time date_time_record_event_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.date_time
    ADD CONSTRAINT date_time_record_event_id_fkey FOREIGN KEY (record_event_id) REFERENCES ord.record_event(id) ON DELETE CASCADE;


--
-- Name: electrochemistry_cell electrochemistry_cell_electrochemistry_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.electrochemistry_cell
    ADD CONSTRAINT electrochemistry_cell_electrochemistry_conditions_id_fkey FOREIGN KEY (electrochemistry_conditions_id) REFERENCES ord.electrochemistry_conditions(id) ON DELETE CASCADE;


--
-- Name: electrochemistry_conditions electrochemistry_conditions_reaction_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.electrochemistry_conditions
    ADD CONSTRAINT electrochemistry_conditions_reaction_conditions_id_fkey FOREIGN KEY (reaction_conditions_id) REFERENCES ord.reaction_conditions(id) ON DELETE CASCADE;


--
-- Name: electrochemistry_measurement electrochemistry_measurement_electrochemistry_conditions_i_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.electrochemistry_measurement
    ADD CONSTRAINT electrochemistry_measurement_electrochemistry_conditions_i_fkey FOREIGN KEY (electrochemistry_conditions_id) REFERENCES ord.electrochemistry_conditions(id) ON DELETE CASCADE;


--
-- Name: float_value float_value_product_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.float_value
    ADD CONSTRAINT float_value_product_measurement_id_fkey FOREIGN KEY (product_measurement_id) REFERENCES ord.product_measurement(id) ON DELETE CASCADE;


--
-- Name: flow_conditions flow_conditions_reaction_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.flow_conditions
    ADD CONSTRAINT flow_conditions_reaction_conditions_id_fkey FOREIGN KEY (reaction_conditions_id) REFERENCES ord.reaction_conditions(id) ON DELETE CASCADE;


--
-- Name: flow_rate flow_rate_reaction_input_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.flow_rate
    ADD CONSTRAINT flow_rate_reaction_input_id_fkey FOREIGN KEY (reaction_input_id) REFERENCES ord.reaction_input(id) ON DELETE CASCADE;


--
-- Name: illumination_conditions illumination_conditions_reaction_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.illumination_conditions
    ADD CONSTRAINT illumination_conditions_reaction_conditions_id_fkey FOREIGN KEY (reaction_conditions_id) REFERENCES ord.reaction_conditions(id) ON DELETE CASCADE;


--
-- Name: reaction_map legacy_reaction_map_ord_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_map
    ADD CONSTRAINT legacy_reaction_map_ord_fkey FOREIGN KEY (ord_reaction_id) REFERENCES ord.reaction(id) ON DELETE RESTRICT;


--
-- Name: reaction_map legacy_reaction_map_reaction_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_map
    ADD CONSTRAINT legacy_reaction_map_reaction_fkey FOREIGN KEY (reaction_id) REFERENCES chemistry.reactions(id) ON DELETE RESTRICT;


--
-- Name: length length_electrochemistry_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.length
    ADD CONSTRAINT length_electrochemistry_conditions_id_fkey FOREIGN KEY (electrochemistry_conditions_id) REFERENCES ord.electrochemistry_conditions(id) ON DELETE CASCADE;


--
-- Name: length length_illumination_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.length
    ADD CONSTRAINT length_illumination_conditions_id_fkey FOREIGN KEY (illumination_conditions_id) REFERENCES ord.illumination_conditions(id) ON DELETE CASCADE;


--
-- Name: length length_tubing_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.length
    ADD CONSTRAINT length_tubing_id_fkey FOREIGN KEY (tubing_id) REFERENCES ord.tubing(id) ON DELETE CASCADE;


--
-- Name: mass mass_amount_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.mass
    ADD CONSTRAINT mass_amount_id_fkey FOREIGN KEY (amount_id) REFERENCES ord.amount(id) ON DELETE CASCADE;


--
-- Name: mass_spec_measurement_details mass_spec_measurement_details_product_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.mass_spec_measurement_details
    ADD CONSTRAINT mass_spec_measurement_details_product_measurement_id_fkey FOREIGN KEY (product_measurement_id) REFERENCES ord.product_measurement(id) ON DELETE CASCADE;


--
-- Name: moles moles_amount_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.moles
    ADD CONSTRAINT moles_amount_id_fkey FOREIGN KEY (amount_id) REFERENCES ord.amount(id) ON DELETE CASCADE;


--
-- Name: percentage percentage_product_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.percentage
    ADD CONSTRAINT percentage_product_measurement_id_fkey FOREIGN KEY (product_measurement_id) REFERENCES ord.product_measurement(id) ON DELETE CASCADE;


--
-- Name: percentage percentage_reaction_outcome_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.percentage
    ADD CONSTRAINT percentage_reaction_outcome_id_fkey FOREIGN KEY (reaction_outcome_id) REFERENCES ord.reaction_outcome(id) ON DELETE CASCADE;


--
-- Name: person person_reaction_provenance_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.person
    ADD CONSTRAINT person_reaction_provenance_id_fkey FOREIGN KEY (reaction_provenance_id) REFERENCES ord.reaction_provenance(id) ON DELETE CASCADE;


--
-- Name: person person_record_event_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.person
    ADD CONSTRAINT person_record_event_id_fkey FOREIGN KEY (record_event_id) REFERENCES ord.record_event(id) ON DELETE CASCADE;


--
-- Name: pressure_conditions pressure_conditions_reaction_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure_conditions
    ADD CONSTRAINT pressure_conditions_reaction_conditions_id_fkey FOREIGN KEY (reaction_conditions_id) REFERENCES ord.reaction_conditions(id) ON DELETE CASCADE;


--
-- Name: pressure_control pressure_control_pressure_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure_control
    ADD CONSTRAINT pressure_control_pressure_conditions_id_fkey FOREIGN KEY (pressure_conditions_id) REFERENCES ord.pressure_conditions(id) ON DELETE CASCADE;


--
-- Name: pressure_measurement pressure_measurement_pressure_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure_measurement
    ADD CONSTRAINT pressure_measurement_pressure_conditions_id_fkey FOREIGN KEY (pressure_conditions_id) REFERENCES ord.pressure_conditions(id) ON DELETE CASCADE;


--
-- Name: pressure pressure_pressure_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure
    ADD CONSTRAINT pressure_pressure_conditions_id_fkey FOREIGN KEY (pressure_conditions_id) REFERENCES ord.pressure_conditions(id) ON DELETE CASCADE;


--
-- Name: pressure pressure_pressure_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.pressure
    ADD CONSTRAINT pressure_pressure_measurement_id_fkey FOREIGN KEY (pressure_measurement_id) REFERENCES ord.pressure_measurement(id) ON DELETE CASCADE;


--
-- Name: product_compound product_compound_chemical_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.product_compound
    ADD CONSTRAINT product_compound_chemical_id_fkey FOREIGN KEY (chemical_id) REFERENCES chemistry.chemicals(id) ON DELETE RESTRICT;


--
-- Name: product_compound product_compound_reaction_outcome_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.product_compound
    ADD CONSTRAINT product_compound_reaction_outcome_id_fkey FOREIGN KEY (reaction_outcome_id) REFERENCES ord.reaction_outcome(id) ON DELETE CASCADE;


--
-- Name: product_measurement product_measurement_product_compound_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.product_measurement
    ADD CONSTRAINT product_measurement_product_compound_id_fkey FOREIGN KEY (product_compound_id) REFERENCES ord.product_compound(id) ON DELETE CASCADE;


--
-- Name: reaction_conditions reaction_conditions_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_conditions
    ADD CONSTRAINT reaction_conditions_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(id) ON DELETE CASCADE;


--
-- Name: reaction reaction_dataset_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction
    ADD CONSTRAINT reaction_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES ord.dataset(id) ON DELETE CASCADE;


--
-- Name: reaction_environment reaction_environment_reaction_setup_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_environment
    ADD CONSTRAINT reaction_environment_reaction_setup_id_fkey FOREIGN KEY (reaction_setup_id) REFERENCES ord.reaction_setup(id) ON DELETE CASCADE;


--
-- Name: reaction_identifier reaction_identifier_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_identifier
    ADD CONSTRAINT reaction_identifier_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(id) ON DELETE CASCADE;


--
-- Name: reaction_input reaction_input_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_input
    ADD CONSTRAINT reaction_input_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(id) ON DELETE CASCADE;


--
-- Name: reaction_input reaction_input_reaction_workup_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_input
    ADD CONSTRAINT reaction_input_reaction_workup_id_fkey FOREIGN KEY (reaction_workup_id) REFERENCES ord.reaction_workup(id) ON DELETE CASCADE;


--
-- Name: reaction_notes reaction_notes_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_notes
    ADD CONSTRAINT reaction_notes_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(id) ON DELETE CASCADE;


--
-- Name: reaction_observation reaction_observation_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_observation
    ADD CONSTRAINT reaction_observation_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(id) ON DELETE CASCADE;


--
-- Name: reaction_outcome reaction_outcome_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_outcome
    ADD CONSTRAINT reaction_outcome_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(id) ON DELETE CASCADE;


--
-- Name: reaction_provenance reaction_provenance_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_provenance
    ADD CONSTRAINT reaction_provenance_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(id) ON DELETE CASCADE;


--
-- Name: reaction_setup reaction_setup_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_setup
    ADD CONSTRAINT reaction_setup_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(id) ON DELETE CASCADE;


--
-- Name: reaction_workup reaction_workup_reaction_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.reaction_workup
    ADD CONSTRAINT reaction_workup_reaction_id_fkey FOREIGN KEY (reaction_id) REFERENCES ord.reaction(id) ON DELETE CASCADE;


--
-- Name: record_event record_event_reaction_provenance_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.record_event
    ADD CONSTRAINT record_event_reaction_provenance_id_fkey FOREIGN KEY (reaction_provenance_id) REFERENCES ord.reaction_provenance(id) ON DELETE CASCADE;


--
-- Name: selectivity selectivity_product_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.selectivity
    ADD CONSTRAINT selectivity_product_measurement_id_fkey FOREIGN KEY (product_measurement_id) REFERENCES ord.product_measurement(id) ON DELETE CASCADE;


--
-- Name: source source_compound_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.source
    ADD CONSTRAINT source_compound_id_fkey FOREIGN KEY (compound_id) REFERENCES ord.compound(id) ON DELETE CASCADE;


--
-- Name: stirring_conditions stirring_conditions_reaction_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.stirring_conditions
    ADD CONSTRAINT stirring_conditions_reaction_conditions_id_fkey FOREIGN KEY (reaction_conditions_id) REFERENCES ord.reaction_conditions(id) ON DELETE CASCADE;


--
-- Name: stirring_conditions stirring_conditions_reaction_workup_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.stirring_conditions
    ADD CONSTRAINT stirring_conditions_reaction_workup_id_fkey FOREIGN KEY (reaction_workup_id) REFERENCES ord.reaction_workup(id) ON DELETE CASCADE;


--
-- Name: stirring_rate stirring_rate_stirring_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.stirring_rate
    ADD CONSTRAINT stirring_rate_stirring_conditions_id_fkey FOREIGN KEY (stirring_conditions_id) REFERENCES ord.stirring_conditions(id) ON DELETE CASCADE;


--
-- Name: temperature_conditions temperature_conditions_reaction_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_conditions
    ADD CONSTRAINT temperature_conditions_reaction_conditions_id_fkey FOREIGN KEY (reaction_conditions_id) REFERENCES ord.reaction_conditions(id) ON DELETE CASCADE;


--
-- Name: temperature_conditions temperature_conditions_reaction_workup_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_conditions
    ADD CONSTRAINT temperature_conditions_reaction_workup_id_fkey FOREIGN KEY (reaction_workup_id) REFERENCES ord.reaction_workup(id) ON DELETE CASCADE;


--
-- Name: temperature_control temperature_control_temperature_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_control
    ADD CONSTRAINT temperature_control_temperature_conditions_id_fkey FOREIGN KEY (temperature_conditions_id) REFERENCES ord.temperature_conditions(id) ON DELETE CASCADE;


--
-- Name: temperature_measurement temperature_measurement_temperature_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature_measurement
    ADD CONSTRAINT temperature_measurement_temperature_conditions_id_fkey FOREIGN KEY (temperature_conditions_id) REFERENCES ord.temperature_conditions(id) ON DELETE CASCADE;


--
-- Name: temperature temperature_reaction_input_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature
    ADD CONSTRAINT temperature_reaction_input_id_fkey FOREIGN KEY (reaction_input_id) REFERENCES ord.reaction_input(id) ON DELETE CASCADE;


--
-- Name: temperature temperature_temperature_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature
    ADD CONSTRAINT temperature_temperature_conditions_id_fkey FOREIGN KEY (temperature_conditions_id) REFERENCES ord.temperature_conditions(id) ON DELETE CASCADE;


--
-- Name: temperature temperature_temperature_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.temperature
    ADD CONSTRAINT temperature_temperature_measurement_id_fkey FOREIGN KEY (temperature_measurement_id) REFERENCES ord.temperature_measurement(id) ON DELETE CASCADE;


--
-- Name: texture texture_compound_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.texture
    ADD CONSTRAINT texture_compound_id_fkey FOREIGN KEY (compound_id) REFERENCES ord.compound(id) ON DELETE CASCADE;


--
-- Name: texture texture_crude_component_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.texture
    ADD CONSTRAINT texture_crude_component_id_fkey FOREIGN KEY (crude_component_id) REFERENCES ord.crude_component(id) ON DELETE CASCADE;


--
-- Name: texture texture_product_compound_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.texture
    ADD CONSTRAINT texture_product_compound_id_fkey FOREIGN KEY (product_compound_id) REFERENCES ord.product_compound(id) ON DELETE CASCADE;


--
-- Name: texture texture_reaction_input_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.texture
    ADD CONSTRAINT texture_reaction_input_id_fkey FOREIGN KEY (reaction_input_id) REFERENCES ord.reaction_input(id) ON DELETE CASCADE;


--
-- Name: time time_electrochemistry_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time"
    ADD CONSTRAINT time_electrochemistry_measurement_id_fkey FOREIGN KEY (electrochemistry_measurement_id) REFERENCES ord.electrochemistry_measurement(id) ON DELETE CASCADE;


--
-- Name: time time_pressure_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time"
    ADD CONSTRAINT time_pressure_measurement_id_fkey FOREIGN KEY (pressure_measurement_id) REFERENCES ord.pressure_measurement(id) ON DELETE CASCADE;


--
-- Name: time time_product_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time"
    ADD CONSTRAINT time_product_measurement_id_fkey FOREIGN KEY (product_measurement_id) REFERENCES ord.product_measurement(id) ON DELETE CASCADE;


--
-- Name: time time_reaction_input_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time"
    ADD CONSTRAINT time_reaction_input_id_fkey FOREIGN KEY (reaction_input_id) REFERENCES ord.reaction_input(id) ON DELETE CASCADE;


--
-- Name: time time_reaction_observation_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time"
    ADD CONSTRAINT time_reaction_observation_id_fkey FOREIGN KEY (reaction_observation_id) REFERENCES ord.reaction_observation(id) ON DELETE CASCADE;


--
-- Name: time time_reaction_outcome_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time"
    ADD CONSTRAINT time_reaction_outcome_id_fkey FOREIGN KEY (reaction_outcome_id) REFERENCES ord.reaction_outcome(id) ON DELETE CASCADE;


--
-- Name: time time_reaction_workup_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time"
    ADD CONSTRAINT time_reaction_workup_id_fkey FOREIGN KEY (reaction_workup_id) REFERENCES ord.reaction_workup(id) ON DELETE CASCADE;


--
-- Name: time time_temperature_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord."time"
    ADD CONSTRAINT time_temperature_measurement_id_fkey FOREIGN KEY (temperature_measurement_id) REFERENCES ord.temperature_measurement(id) ON DELETE CASCADE;


--
-- Name: tubing tubing_flow_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.tubing
    ADD CONSTRAINT tubing_flow_conditions_id_fkey FOREIGN KEY (flow_conditions_id) REFERENCES ord.flow_conditions(id) ON DELETE CASCADE;


--
-- Name: unmeasured_amount unmeasured_amount_amount_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.unmeasured_amount
    ADD CONSTRAINT unmeasured_amount_amount_id_fkey FOREIGN KEY (amount_id) REFERENCES ord.amount(id) ON DELETE CASCADE;


--
-- Name: vessel_attachment vessel_attachment_vessel_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel_attachment
    ADD CONSTRAINT vessel_attachment_vessel_id_fkey FOREIGN KEY (vessel_id) REFERENCES ord.vessel(id) ON DELETE CASCADE;


--
-- Name: vessel_material vessel_material_vessel_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel_material
    ADD CONSTRAINT vessel_material_vessel_id_fkey FOREIGN KEY (vessel_id) REFERENCES ord.vessel(id) ON DELETE CASCADE;


--
-- Name: vessel_preparation vessel_preparation_vessel_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel_preparation
    ADD CONSTRAINT vessel_preparation_vessel_id_fkey FOREIGN KEY (vessel_id) REFERENCES ord.vessel(id) ON DELETE CASCADE;


--
-- Name: vessel vessel_reaction_setup_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.vessel
    ADD CONSTRAINT vessel_reaction_setup_id_fkey FOREIGN KEY (reaction_setup_id) REFERENCES ord.reaction_setup(id) ON DELETE CASCADE;


--
-- Name: voltage voltage_electrochemistry_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.voltage
    ADD CONSTRAINT voltage_electrochemistry_conditions_id_fkey FOREIGN KEY (electrochemistry_conditions_id) REFERENCES ord.electrochemistry_conditions(id) ON DELETE CASCADE;


--
-- Name: voltage voltage_electrochemistry_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.voltage
    ADD CONSTRAINT voltage_electrochemistry_measurement_id_fkey FOREIGN KEY (electrochemistry_measurement_id) REFERENCES ord.electrochemistry_measurement(id) ON DELETE CASCADE;


--
-- Name: volume volume_amount_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.volume
    ADD CONSTRAINT volume_amount_id_fkey FOREIGN KEY (amount_id) REFERENCES ord.amount(id) ON DELETE CASCADE;


--
-- Name: volume volume_vessel_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.volume
    ADD CONSTRAINT volume_vessel_id_fkey FOREIGN KEY (vessel_id) REFERENCES ord.vessel(id) ON DELETE CASCADE;


--
-- Name: wavelength wavelength_illumination_conditions_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.wavelength
    ADD CONSTRAINT wavelength_illumination_conditions_id_fkey FOREIGN KEY (illumination_conditions_id) REFERENCES ord.illumination_conditions(id) ON DELETE CASCADE;


--
-- Name: wavelength wavelength_product_measurement_id_fkey; Type: FK CONSTRAINT; Schema: ord; Owner: -
--

ALTER TABLE ONLY ord.wavelength
    ADD CONSTRAINT wavelength_product_measurement_id_fkey FOREIGN KEY (product_measurement_id) REFERENCES ord.product_measurement(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict heaavEZI2Lyll5yaWSbJdyvZTzcRir5zeofKT9HYo6Koeqwwp3mkU9JR1kjKHSL

