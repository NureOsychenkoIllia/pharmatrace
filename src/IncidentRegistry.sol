// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

import {IParticipantRegistry} from "./interfaces/IParticipantRegistry.sol";
import {IBatchToken} from "./interfaces/IBatchToken.sol";

/// @title Incidents, model decisions and recalls
/// @notice Participants report anomalies; the oracle attaches a model decision;
///         the regulator confirms the incident and the batch is recalled.
contract IncidentRegistry is AccessControl, Pausable {
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");
    bytes32 public constant VERIFIER_ROLE = keccak256("VERIFIER_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");

    /// @notice Incident category
    enum IncidentKind {
        None,
        RouteAnomaly,
        Counterfeit,
        RecallRequest,
        CustodyDispute
    }

    /// @notice Incident severity
    enum Severity {
        None,
        Low,
        Medium,
        High,
        Critical
    }

    /// @notice Incident workflow state
    enum Status {
        None,
        Open,
        ModelReviewed,
        Confirmed,
        Dismissed,
        Resolved
    }

    /// @notice Incident record
    struct Incident {
        uint256 batchId;
        IncidentKind kind;
        Severity severity;
        Status status;
        address reporter;
        uint64 createdAt;
        uint16 scoreBps;
        bytes32 modelVersion;
        bytes32 dataHash;
        bytes32 noteHash;
    }

    uint16 public constant MAX_SCORE_BPS = 10_000;
    uint8 private constant BATCH_RECALLED = 5;
    uint8 private constant BATCH_DESTROYED = 6;

    IParticipantRegistry public immutable REGISTRY;
    IBatchToken public immutable BATCH;

    address public oracle;
    uint256 public incidentCount;
    mapping(uint256 => Incident) private _incidents;
    mapping(uint256 => uint256[]) private _byBatch;
    /// @notice Whether an oracle registered the hash of a model artifact.
    mapping(bytes32 => bool) public registeredModels;

    event IncidentReported(
        uint256 indexed incidentId,
        uint256 indexed batchId,
        IncidentKind kind,
        Severity severity,
        address indexed reporter
    );
    event ModelDecisionRecorded(
        uint256 indexed incidentId, uint16 scoreBps, bytes32 modelVersion, bytes32 dataHash
    );
    event IncidentConfirmed(uint256 indexed incidentId, address indexed verifier);
    event IncidentDismissed(uint256 indexed incidentId, address indexed verifier);
    event IncidentResolved(uint256 indexed incidentId, address indexed verifier);
    event OracleUpdated(address indexed oldOracle, address indexed newOracle);
    event ModelRegistered(bytes32 indexed modelVersion, address indexed oracle);

    error ZeroAddress();
    error InvalidKind();
    error InvalidSeverity();
    error EmptyNote();
    error NotParticipant(address account);
    error IncidentNotFound(uint256 incidentId);
    error InvalidTransition(uint256 incidentId, Status status);
    error InvalidScore(uint16 scoreBps);
    error BatchNotFound(uint256 batchId);
    error EmptyModelVersion();

    /// @param admin Receives admin and pauser roles
    /// @param verifier Receives the verifier role
    /// @param registry Participant registry
    /// @param batch Batch token contract
    /// @param initialOracle Initial oracle address
    constructor(
        address admin,
        address verifier,
        IParticipantRegistry registry,
        IBatchToken batch,
        address initialOracle
    ) {
        if (
            admin == address(0) || verifier == address(0) || address(registry) == address(0)
                || address(batch) == address(0)
        ) revert ZeroAddress();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);
        _grantRole(VERIFIER_ROLE, verifier);
        REGISTRY = registry;
        BATCH = batch;
        if (initialOracle != address(0)) _setOracle(initialOracle);
    }

    /// @notice Registers a model artifact hash for the audit trail.
    /// @param modelVersion SHA-256 of the model artifact.
    function registerModel(bytes32 modelVersion) external onlyRole(ORACLE_ROLE) whenNotPaused {
        if (modelVersion == bytes32(0)) revert EmptyModelVersion();
        if (registeredModels[modelVersion]) return;
        registeredModels[modelVersion] = true;
        emit ModelRegistered(modelVersion, msg.sender);
    }

    /// @notice Reports an incident without a model decision yet
    /// @param batchId Batch identifier
    /// @param kind Incident category
    /// @param severity Initial severity
    /// @param noteHash Hash of the incident description
    function reportIncident(uint256 batchId, IncidentKind kind, Severity severity, bytes32 noteHash)
        external
        whenNotPaused
        returns (uint256 incidentId)
    {
        if (!REGISTRY.isActiveParticipant(msg.sender)) revert NotParticipant(msg.sender);
        incidentId = _create(batchId, kind, severity, noteHash, Status.Open, 0, 0, 0);
        emit IncidentReported(incidentId, batchId, kind, severity, msg.sender);
    }

    /// @notice Creates a reviewed incident from an oracle decision
    /// @param batchId Batch identifier
    /// @param kind Incident category
    /// @param severity Model severity
    /// @param scoreBps Anomaly score in basis points
    /// @param modelVersion Hash of the model artefact
    /// @param dataHash Hash of the feature vector
    /// @param noteHash Hash of the explanation document
    function reportOracleIncident(
        uint256 batchId,
        IncidentKind kind,
        Severity severity,
        uint16 scoreBps,
        bytes32 modelVersion,
        bytes32 dataHash,
        bytes32 noteHash
    ) external onlyRole(ORACLE_ROLE) whenNotPaused returns (uint256 incidentId) {
        if (scoreBps > MAX_SCORE_BPS) revert InvalidScore(scoreBps);
        incidentId = _create(
            batchId,
            kind,
            severity,
            noteHash,
            Status.ModelReviewed,
            scoreBps,
            modelVersion,
            dataHash
        );
        emit IncidentReported(incidentId, batchId, kind, severity, msg.sender);
        emit ModelDecisionRecorded(incidentId, scoreBps, modelVersion, dataHash);
    }

    /// @notice Attaches an oracle decision to an open incident
    /// @param incidentId Incident identifier
    /// @param scoreBps Anomaly score in basis points
    /// @param modelVersion Hash of the model artefact
    /// @param dataHash Hash of the feature vector
    function submitModelDecision(
        uint256 incidentId,
        uint16 scoreBps,
        bytes32 modelVersion,
        bytes32 dataHash
    ) external onlyRole(ORACLE_ROLE) whenNotPaused {
        if (scoreBps > MAX_SCORE_BPS) revert InvalidScore(scoreBps);
        Incident storage incident = _incident(incidentId);
        if (incident.status != Status.Open) revert InvalidTransition(incidentId, incident.status);
        incident.scoreBps = scoreBps;
        incident.modelVersion = modelVersion;
        incident.dataHash = dataHash;
        incident.status = Status.ModelReviewed;
        emit ModelDecisionRecorded(incidentId, scoreBps, modelVersion, dataHash);
    }

    /// @notice Confirms a reviewed incident and recalls the batch
    /// @param incidentId Incident identifier
    function confirmIncident(uint256 incidentId) external onlyRole(VERIFIER_ROLE) whenNotPaused {
        Incident storage incident = _incident(incidentId);
        if (incident.status != Status.ModelReviewed) {
            revert InvalidTransition(incidentId, incident.status);
        }
        incident.status = Status.Confirmed;
        emit IncidentConfirmed(incidentId, msg.sender);

        uint8 batchState = BATCH.batchState(incident.batchId);
        if (batchState != BATCH_RECALLED && batchState != BATCH_DESTROYED) {
            BATCH.recallByIncident(incident.batchId, incident.noteHash);
        }
    }

    /// @notice Dismisses a reviewed incident
    /// @param incidentId Incident identifier
    function dismissIncident(uint256 incidentId) external onlyRole(VERIFIER_ROLE) whenNotPaused {
        Incident storage incident = _incident(incidentId);
        if (incident.status != Status.ModelReviewed) {
            revert InvalidTransition(incidentId, incident.status);
        }
        incident.status = Status.Dismissed;
        emit IncidentDismissed(incidentId, msg.sender);
    }

    /// @notice Resolves a confirmed incident after the recall is complete
    /// @param incidentId Incident identifier
    function resolveIncident(uint256 incidentId) external onlyRole(VERIFIER_ROLE) whenNotPaused {
        Incident storage incident = _incident(incidentId);
        if (incident.status != Status.Confirmed) {
            revert InvalidTransition(incidentId, incident.status);
        }
        incident.status = Status.Resolved;
        emit IncidentResolved(incidentId, msg.sender);
    }

    /// @notice Replaces the oracle address
    /// @param newOracle New oracle
    function setOracle(address newOracle) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _setOracle(newOracle);
    }

    /// @notice Pauses incident processing
    function pause() external onlyRole(PAUSER_ROLE) {
        _pause();
    }

    /// @notice Resumes incident processing
    function unpause() external onlyRole(PAUSER_ROLE) {
        _unpause();
    }

    /// @notice Returns the incident record
    function getIncident(uint256 incidentId) external view returns (Incident memory) {
        if (incidentId == 0 || incidentId > incidentCount) revert IncidentNotFound(incidentId);
        return _incidents[incidentId];
    }

    /// @notice Incident identifiers of a batch
    function incidentsByBatch(uint256 batchId) external view returns (uint256[] memory) {
        return _byBatch[batchId];
    }

    /// @dev Validates and stores a new incident
    function _create(
        uint256 batchId,
        IncidentKind kind,
        Severity severity,
        bytes32 noteHash,
        Status status,
        uint16 scoreBps,
        bytes32 modelVersion,
        bytes32 dataHash
    ) private returns (uint256 incidentId) {
        if (kind == IncidentKind.None) revert InvalidKind();
        if (severity == Severity.None) revert InvalidSeverity();
        if (noteHash == bytes32(0)) revert EmptyNote();
        if (batchId == 0) revert BatchNotFound(batchId);
        try BATCH.batchState(batchId) returns (uint8 state) {
            if (state == 0) revert BatchNotFound(batchId);
        } catch {
            revert BatchNotFound(batchId);
        }

        incidentId = ++incidentCount;
        _incidents[incidentId] = Incident({
            batchId: batchId,
            kind: kind,
            severity: severity,
            status: status,
            reporter: msg.sender,
            createdAt: uint64(block.timestamp),
            scoreBps: scoreBps,
            modelVersion: modelVersion,
            dataHash: dataHash,
            noteHash: noteHash
        });
        _byBatch[batchId].push(incidentId);
    }

    /// @dev Returns the incident and checks that it exists
    function _incident(uint256 incidentId) private view returns (Incident storage incident) {
        if (incidentId == 0 || incidentId > incidentCount) revert IncidentNotFound(incidentId);
        incident = _incidents[incidentId];
    }

    /// @dev Replaces the oracle and its role
    function _setOracle(address newOracle) private {
        if (newOracle == address(0)) revert ZeroAddress();
        address old = oracle;
        if (old != address(0)) _revokeRole(ORACLE_ROLE, old);
        oracle = newOracle;
        _grantRole(ORACLE_ROLE, newOracle);
        emit OracleUpdated(old, newOracle);
    }
}
