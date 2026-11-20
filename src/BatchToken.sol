// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

import {IParticipantRegistry} from "./interfaces/IParticipantRegistry.sol";
import {IBatchToken} from "./interfaces/IBatchToken.sol";

/// @title Drug batch as a non-fungible token
/// @notice Each batch moves through a custody state machine; every handover is recorded.
/// @dev Transfers are disabled: custody changes only through initiate/accept.
contract BatchToken is ERC721, AccessControl, Pausable, IBatchToken {
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");
    bytes32 public constant INCIDENT_ROLE = keccak256("INCIDENT_ROLE");

    /// @notice Batch lifecycle state
    enum State {
        None,
        Created,
        InTransit,
        Delivered,
        Dispensed,
        Recalled,
        Destroyed
    }

    /// @notice Batch record
    /// @dev Fields are ordered to fit eight storage slots
    struct Batch {
        bytes32 productId;
        bytes32 metadataHash;
        bytes32 modelVersion;
        bytes32 dataHash;
        address manufacturer;
        uint64 serial;
        uint16 anomalyScore;
        bool flagged;
        State state;
        address custodian;
        uint64 expiry;
        bytes2 originCity;
        address pendingRecipient;
        uint64 createdAt;
        uint128 quantity;
        uint128 parentId;
    }

    /// @notice Read model for lists
    struct BatchView {
        uint256 id;
        bytes32 productId;
        uint64 serial;
        address manufacturer;
        address custodian;
        uint64 expiry;
        uint64 createdAt;
        State state;
        uint128 quantity;
        uint128 parentId;
        bytes32 metadataHash;
        bytes2 originCity;
        bool flagged;
        uint16 anomalyScore;
    }

    uint16 public constant MAX_SCORE_BPS = 10_000;
    uint64 public constant SPLIT_SERIAL_BASE = 1_000_000;
    uint256 public constant MAX_SPLIT = 50;

    IParticipantRegistry public immutable REGISTRY;

    address public oracle;
    uint16 public thresholdBps;
    uint256 public batchCount;
    uint64 public splitSerialCounter;
    bool private _custodyMoving;

    mapping(uint256 => Batch) private _batches;
    mapping(bytes32 => mapping(uint64 => uint256)) private _serialIndex;
    mapping(uint256 => bytes32) public patientCommitment;

    event BatchMinted(
        uint256 indexed tokenId,
        bytes32 indexed productId,
        uint64 serial,
        address indexed manufacturer,
        uint128 quantity,
        bytes32 metadataHash
    );
    event CustodyInitiated(
        uint256 indexed tokenId, address indexed from, address indexed to, bytes2 city
    );
    event CustodyAccepted(uint256 indexed tokenId, address indexed from, address indexed to);
    event CustodyRejected(uint256 indexed tokenId, address indexed from, address indexed to);
    event BatchSplit(
        uint256 indexed parentId,
        uint256[] childIds,
        uint128[] quantities,
        address indexed custodian
    );
    event BatchDispensed(
        uint256 indexed tokenId, address indexed pharmacy, bytes32 patientCommitment
    );
    event BatchRecalled(uint256 indexed tokenId, address indexed by, bytes32 reasonHash);
    event BatchDestroyed(uint256 indexed tokenId, address indexed by);
    event AnomalyRecorded(
        uint256 indexed tokenId,
        uint16 scoreBps,
        bytes32 modelVersion,
        bytes32 dataHash,
        uint8 anomalyType
    );
    event OracleUpdated(address indexed oldOracle, address indexed newOracle);
    event ThresholdUpdated(uint16 oldThresholdBps, uint16 newThresholdBps);

    error ZeroAddress();
    error NotManufacturer(address account);
    error NotCustodian(uint256 tokenId, address account);
    error InvalidRecipient(address account);
    error InvalidQuantity();
    error InvalidExpiry();
    error DuplicateSerial(bytes32 productId, uint64 serial);
    error BatchNotFound(uint256 tokenId);
    error InvalidState(uint256 tokenId, State state);
    error NotPendingRecipient(uint256 tokenId, address account);
    error NotPharmacy(address account);
    error InvalidScore(uint16 scoreBps);
    error InvalidSplit();
    error NotRecallable(uint256 tokenId);
    error UseCustodyWorkflow();
    error InvalidThreshold(uint16 thresholdBps);

    /// @param admin Receives admin and pauser roles
    /// @param registry Participant registry
    /// @param initialOracle Oracle address
    /// @param initialThresholdBps Score threshold in basis points
    constructor(
        address admin,
        IParticipantRegistry registry,
        address initialOracle,
        uint16 initialThresholdBps
    ) ERC721("PharmaBatch", "PBATCH") {
        if (admin == address(0) || address(registry) == address(0)) {
            revert ZeroAddress();
        }
        if (initialThresholdBps > MAX_SCORE_BPS) revert InvalidThreshold(initialThresholdBps);
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);
        REGISTRY = registry;
        thresholdBps = initialThresholdBps;
        if (initialOracle != address(0)) _setOracle(initialOracle);
    }

    /// @notice Mints a new batch to its manufacturer
    /// @param productId Hash of the product identifier
    /// @param serial Package serial number, unique per product
    /// @param expiry Expiry timestamp
    /// @param quantity Number of packages
    /// @param metadataHash Hash of the off-chain batch document
    /// @param originCity Two-letter city code
    function mint(
        bytes32 productId,
        uint64 serial,
        uint64 expiry,
        uint128 quantity,
        bytes32 metadataHash,
        bytes2 originCity
    ) external whenNotPaused returns (uint256 tokenId) {
        if (!REGISTRY.isActive(msg.sender, IParticipantRegistry.Kind.Manufacturer)) {
            revert NotManufacturer(msg.sender);
        }
        if (quantity == 0) revert InvalidQuantity();
        if (expiry <= block.timestamp) revert InvalidExpiry();
        if (_serialIndex[productId][serial] != 0) revert DuplicateSerial(productId, serial);

        tokenId = ++batchCount;
        _serialIndex[productId][serial] = tokenId;
        _batches[tokenId] = Batch({
            productId: productId,
            serial: serial,
            manufacturer: msg.sender,
            custodian: msg.sender,
            expiry: expiry,
            createdAt: uint64(block.timestamp),
            state: State.Created,
            pendingRecipient: address(0),
            quantity: quantity,
            parentId: 0,
            metadataHash: metadataHash,
            originCity: originCity,
            flagged: false,
            anomalyScore: 0,
            modelVersion: bytes32(0),
            dataHash: bytes32(0)
        });
        _mint(msg.sender, tokenId);
        emit BatchMinted(tokenId, productId, serial, msg.sender, quantity, metadataHash);
    }

    /// @notice Starts a custody handover
    /// @param tokenId Batch identifier
    /// @param to Next custodian
    /// @param city Destination city code
    function initiateCustody(uint256 tokenId, address to, bytes2 city) external whenNotPaused {
        Batch storage batch = _batch(tokenId);
        if (batch.custodian != msg.sender) revert NotCustodian(tokenId, msg.sender);
        if (batch.state != State.Created && batch.state != State.Delivered) {
            revert InvalidState(tokenId, batch.state);
        }
        if (city == bytes2(0)) revert InvalidRecipient(to);
        if (to == msg.sender || to == address(0)) revert InvalidRecipient(to);

        IParticipantRegistry.Kind senderKind = _kind(msg.sender);
        if (
            senderKind != IParticipantRegistry.Kind.Manufacturer
                && senderKind != IParticipantRegistry.Kind.Distributor
        ) revert InvalidRecipient(msg.sender);

        IParticipantRegistry.Kind recipientKind = _kind(to);
        if (!REGISTRY.isActive(to, recipientKind)) revert InvalidRecipient(to);
        if (
            recipientKind != IParticipantRegistry.Kind.Distributor
                && recipientKind != IParticipantRegistry.Kind.Pharmacy
        ) revert InvalidRecipient(to);

        batch.pendingRecipient = to;
        batch.state = State.InTransit;
        emit CustodyInitiated(tokenId, msg.sender, to, city);
    }

    /// @notice Accepts an incoming handover
    /// @param tokenId Batch identifier
    function acceptCustody(uint256 tokenId) external whenNotPaused {
        Batch storage batch = _batch(tokenId);
        if (batch.state != State.InTransit) revert InvalidState(tokenId, batch.state);
        if (batch.pendingRecipient != msg.sender) revert NotPendingRecipient(tokenId, msg.sender);
        if (!REGISTRY.isActiveParticipant(msg.sender)) revert InvalidRecipient(msg.sender);

        address previous = batch.custodian;
        batch.custodian = msg.sender;
        batch.pendingRecipient = address(0);
        batch.state = State.Delivered;
        _custodyMoving = true;
        _transfer(previous, msg.sender, tokenId);
        _custodyMoving = false;
        emit CustodyAccepted(tokenId, previous, msg.sender);
    }

    /// @notice Rejects an incoming handover and returns the batch to the sender
    /// @param tokenId Batch identifier
    function rejectCustody(uint256 tokenId) external whenNotPaused {
        Batch storage batch = _batch(tokenId);
        if (batch.state != State.InTransit) revert InvalidState(tokenId, batch.state);
        if (batch.pendingRecipient != msg.sender) revert NotPendingRecipient(tokenId, msg.sender);
        batch.pendingRecipient = address(0);
        batch.state = State.Delivered;
        emit CustodyRejected(tokenId, batch.custodian, msg.sender);
    }

    /// @notice Splits a batch into sub-batches with new serials
    /// @param tokenId Parent batch
    /// @param quantities Quantities of the children
    function split(uint256 tokenId, uint128[] calldata quantities)
        external
        whenNotPaused
        returns (uint256[] memory childIds)
    {
        Batch storage parent = _batch(tokenId);
        if (parent.custodian != msg.sender) revert NotCustodian(tokenId, msg.sender);
        if (parent.state != State.Created && parent.state != State.Delivered) {
            revert InvalidState(tokenId, parent.state);
        }
        if (quantities.length == 0 || quantities.length > MAX_SPLIT) revert InvalidSplit();

        uint128 total = 0;
        for (uint256 i = 0; i < quantities.length; i++) {
            if (quantities[i] == 0) revert InvalidSplit();
            total += quantities[i];
        }
        if (total > parent.quantity) revert InvalidSplit();

        parent.quantity -= total;
        childIds = new uint256[](quantities.length);
        for (uint256 i = 0; i < quantities.length; i++) {
            uint256 childId = ++batchCount;
            uint64 childSerial = ++splitSerialCounter + SPLIT_SERIAL_BASE;
            _serialIndex[parent.productId][childSerial] = childId;
            _batches[childId] = Batch({
                productId: parent.productId,
                serial: childSerial,
                manufacturer: parent.manufacturer,
                custodian: msg.sender,
                expiry: parent.expiry,
                createdAt: uint64(block.timestamp),
                state: parent.state,
                pendingRecipient: address(0),
                quantity: quantities[i],
                parentId: uint128(tokenId),
                metadataHash: parent.metadataHash,
                originCity: parent.originCity,
                flagged: parent.flagged,
                anomalyScore: parent.anomalyScore,
                modelVersion: parent.modelVersion,
                dataHash: parent.dataHash
            });
            _mint(msg.sender, childId);
            childIds[i] = childId;
        }
        emit BatchSplit(tokenId, childIds, quantities, msg.sender);
    }

    /// @notice Dispenses a batch at a pharmacy
    /// @param tokenId Batch identifier
    /// @param commitment Hash of the patient's pseudonymous commitment
    function dispense(uint256 tokenId, bytes32 commitment) external whenNotPaused {
        Batch storage batch = _batch(tokenId);
        if (batch.custodian != msg.sender) revert NotCustodian(tokenId, msg.sender);
        if (batch.state != State.Delivered) revert InvalidState(tokenId, batch.state);
        if (!REGISTRY.isActive(msg.sender, IParticipantRegistry.Kind.Pharmacy)) {
            revert NotPharmacy(msg.sender);
        }
        if (commitment == bytes32(0)) revert InvalidQuantity();

        batch.state = State.Dispensed;
        patientCommitment[tokenId] = commitment;
        emit BatchDispensed(tokenId, msg.sender, commitment);
    }

    /// @notice Recalls a batch
    /// @param tokenId Batch identifier
    /// @param reasonHash Hash of the recall document
    function recall(uint256 tokenId, bytes32 reasonHash) external whenNotPaused {
        Batch storage batch = _batch(tokenId);
        bool regulator = REGISTRY.isActive(msg.sender, IParticipantRegistry.Kind.Regulator)
            || hasRole(DEFAULT_ADMIN_ROLE, msg.sender);
        bool manufacturer = msg.sender == batch.manufacturer;
        if (!regulator && !manufacturer) revert NotManufacturer(msg.sender);
        _recall(tokenId, reasonHash);
    }

    /// @notice Recalls a batch on behalf of the incident registry
    /// @param tokenId Batch identifier
    /// @param reasonHash Hash of the recall document
    function recallByIncident(uint256 tokenId, bytes32 reasonHash)
        external
        override
        onlyRole(INCIDENT_ROLE)
        whenNotPaused
    {
        _recall(tokenId, reasonHash);
    }

    /// @notice Destroys a recalled batch
    /// @param tokenId Batch identifier
    function destroy(uint256 tokenId) external whenNotPaused {
        Batch storage batch = _batch(tokenId);
        if (batch.custodian != msg.sender) revert NotCustodian(tokenId, msg.sender);
        if (batch.state != State.Recalled) revert InvalidState(tokenId, batch.state);
        batch.state = State.Destroyed;
        emit BatchDestroyed(tokenId, msg.sender);
    }

    /// @notice Stores a model decision about a batch
    /// @param tokenId Batch identifier
    /// @param scoreBps Anomaly score in basis points
    /// @param modelVersion Hash of the model artefact
    /// @param dataHash Hash of the feature vector
    /// @param anomalyType Numeric anomaly class
    function recordAnomaly(
        uint256 tokenId,
        uint16 scoreBps,
        bytes32 modelVersion,
        bytes32 dataHash,
        uint8 anomalyType
    ) external onlyRole(ORACLE_ROLE) whenNotPaused {
        if (scoreBps > MAX_SCORE_BPS) revert InvalidScore(scoreBps);
        Batch storage batch = _batch(tokenId);
        batch.anomalyScore = scoreBps;
        batch.modelVersion = modelVersion;
        batch.dataHash = dataHash;
        batch.flagged = scoreBps >= thresholdBps;
        emit AnomalyRecorded(tokenId, scoreBps, modelVersion, dataHash, anomalyType);
    }

    /// @notice Replaces the oracle address
    /// @param newOracle New oracle
    function setOracle(address newOracle) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _setOracle(newOracle);
    }

    /// @notice Updates the anomaly threshold
    /// @param newThresholdBps New threshold in basis points
    function setThresholdBps(uint16 newThresholdBps) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (newThresholdBps > MAX_SCORE_BPS) revert InvalidThreshold(newThresholdBps);
        uint16 old = thresholdBps;
        thresholdBps = newThresholdBps;
        emit ThresholdUpdated(old, newThresholdBps);
    }

    /// @notice Pauses minting and custody operations
    function pause() external onlyRole(PAUSER_ROLE) {
        _pause();
    }

    /// @notice Resumes operations
    function unpause() external onlyRole(PAUSER_ROLE) {
        _unpause();
    }

    /// @notice Returns the batch record
    function getBatch(uint256 tokenId) external view returns (Batch memory) {
        if (tokenId == 0 || tokenId > batchCount) revert BatchNotFound(tokenId);
        return _batches[tokenId];
    }

    /// @notice Returns a batch state
    function stateOf(uint256 tokenId) external view returns (State) {
        if (tokenId == 0 || tokenId > batchCount) revert BatchNotFound(tokenId);
        return _batches[tokenId].state;
    }

    /// @notice Returns the batch state as its numeric enum value
    function batchState(uint256 tokenId) external view override returns (uint8) {
        if (tokenId == 0 || tokenId > batchCount) revert BatchNotFound(tokenId);
        return uint8(_batches[tokenId].state);
    }

    /// @notice Returns the remaining quantity of a batch
    function quantityOf(uint256 tokenId) external view returns (uint128) {
        if (tokenId == 0 || tokenId > batchCount) revert BatchNotFound(tokenId);
        return _batches[tokenId].quantity;
    }

    /// @notice Returns the last model decision about a batch
    function anomalyOf(uint256 tokenId)
        external
        view
        returns (uint16 scoreBps, bool flagged, bytes32 modelVersion, bytes32 dataHash)
    {
        if (tokenId == 0 || tokenId > batchCount) revert BatchNotFound(tokenId);
        Batch storage batch = _batches[tokenId];
        return (batch.anomalyScore, batch.flagged, batch.modelVersion, batch.dataHash);
    }

    /// @notice Looks up a batch by product and serial
    /// @return tokenId Zero when the serial is unknown
    function verifySerial(bytes32 productId, uint64 serial) external view returns (uint256) {
        return _serialIndex[productId][serial];
    }

    /// @notice Paginated batch list
    /// @param offset First token id
    /// @param limit Maximum number of entries
    function getBatches(uint256 offset, uint256 limit)
        external
        view
        returns (BatchView[] memory page)
    {
        uint256 start = offset == 0 ? 1 : offset;
        uint256 end = start + limit;
        if (end > batchCount + 1) end = batchCount + 1;
        if (start >= end) return new BatchView[](0);
        page = new BatchView[](end - start);
        for (uint256 id = start; id < end; id++) {
            Batch storage batch = _batches[id];
            page[id - start] = BatchView({
                id: id,
                productId: batch.productId,
                serial: batch.serial,
                manufacturer: batch.manufacturer,
                custodian: batch.custodian,
                expiry: batch.expiry,
                createdAt: batch.createdAt,
                state: batch.state,
                quantity: batch.quantity,
                parentId: batch.parentId,
                metadataHash: batch.metadataHash,
                originCity: batch.originCity,
                flagged: batch.flagged,
                anomalyScore: batch.anomalyScore
            });
        }
    }

    /// @notice ERC-721 transfers are disabled; custody uses initiate/accept
    function _update(address to, uint256 tokenId, address auth)
        internal
        override
        returns (address)
    {
        address from = _ownerOf(tokenId);
        if (!_custodyMoving && from != address(0) && to != address(0)) {
            revert UseCustodyWorkflow();
        }
        return super._update(to, tokenId, auth);
    }

    /// @notice Resolves the ERC-165 conflict between ERC721 and AccessControl
    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }

    /// @dev Returns the batch and checks that it exists
    function _batch(uint256 tokenId) private view returns (Batch storage batch) {
        if (tokenId == 0 || tokenId > batchCount) revert BatchNotFound(tokenId);
        batch = _batches[tokenId];
    }

    /// @dev Maps a participant kind from the registry
    function _kind(address account) private view returns (IParticipantRegistry.Kind kind) {
        kind = REGISTRY.kindOf(account);
    }

    /// @dev Shared recall path
    function _recall(uint256 tokenId, bytes32 reasonHash) private {
        Batch storage batch = _batch(tokenId);
        if (
            batch.state != State.Created && batch.state != State.InTransit
                && batch.state != State.Delivered && batch.state != State.Dispensed
        ) revert NotRecallable(tokenId);
        batch.state = State.Recalled;
        batch.pendingRecipient = address(0);
        emit BatchRecalled(tokenId, msg.sender, reasonHash);
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
