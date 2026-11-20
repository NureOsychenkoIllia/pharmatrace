// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script, console2} from "forge-std/Script.sol";
import {ParticipantRegistry} from "../src/ParticipantRegistry.sol";
import {BatchToken} from "../src/BatchToken.sol";
import {IncidentRegistry} from "../src/IncidentRegistry.sol";
import {IBatchToken} from "../src/interfaces/IBatchToken.sol";

/// @notice Deploys the three contracts and writes addresses to deployments/<chainId>.json.
/// @dev Reads PRIVATE_KEY, VERIFIER, ORACLE and THRESHOLD_BPS from the environment.
contract Deploy is Script {
    function run()
        external
        returns (ParticipantRegistry registry, BatchToken batch, IncidentRegistry incidents)
    {
        uint256 privateKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(privateKey);
        address verifier = vm.envOr("VERIFIER", deployer);
        address oracle = vm.envOr("ORACLE", deployer);
        uint16 thresholdBps = uint16(vm.envOr("THRESHOLD_BPS", uint256(7_000)));

        vm.startBroadcast(privateKey);
        registry = new ParticipantRegistry(deployer, verifier);
        batch = new BatchToken(deployer, registry, oracle, thresholdBps);
        incidents =
            new IncidentRegistry(deployer, verifier, registry, IBatchToken(address(batch)), oracle);
        batch.grantRole(batch.INCIDENT_ROLE(), address(incidents));
        vm.stopBroadcast();

        console2.log("deployer", deployer);
        console2.log("verifier", verifier);
        console2.log("oracle", oracle);
        console2.log("thresholdBps", thresholdBps);
        console2.log("ParticipantRegistry", address(registry));
        console2.log("BatchToken", address(batch));
        console2.log("IncidentRegistry", address(incidents));

        string memory obj = "deployment";
        vm.serializeUint(obj, "chainId", block.chainid);
        vm.serializeAddress(obj, "deployer", deployer);
        vm.serializeAddress(obj, "verifier", verifier);
        vm.serializeAddress(obj, "oracle", oracle);
        vm.serializeUint(obj, "thresholdBps", thresholdBps);
        vm.serializeAddress(obj, "registry", address(registry));
        vm.serializeAddress(obj, "batch", address(batch));
        string memory json = vm.serializeAddress(obj, "incidents", address(incidents));
        vm.writeJson(json, string.concat("./deployments/", vm.toString(block.chainid), ".json"));
    }
}
