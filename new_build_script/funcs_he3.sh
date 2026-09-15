_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

#Just prints
function printParams()
{
	echo FLASH=$FLASH
	echo TYPE=$TYPE
	echo BOARD=$BOARD
	echo CUSTOMER=$CUSTOMER
	echo SHA=$SHA
	return 0
}

#Returns 99 if something is wrong
function isValid()
{
		local toSearch="$1"
		shift
		local list=("$@")

		for item in "${list[@]}"; do
				if [[ "$item" == "$toSearch" ]]; then
						return 0
				fi
		done
		return 99
}

function isError()
{
	# Capture $? first: every command below (including `echo`) overwrites it.
	local rc=$?
	if [[ "$rc" -ne 0 ]]; then
		echo "Error!!! code $1 (exit status $rc)"
		# FIX: this was a bare `exit`, which exits with the status of the
		# preceding `echo` -- i.e. 0. Every failure this guard caught was
		# reported to the caller (Jenkins, ci_build.sh, cron) as SUCCESS.
		exit "$rc"
	fi
}

#Check if params are valid
function checkParams()
{
	isValid $FLASH "${FLASHLIST[@]}"
	isError $LINENO
	isValid $BOARD "${BOARDLIST[@]}"
	isError $LINENO
	isValid $CUSTOMER "${CUSTOMERLIST[@]}"
	isError $LINENO
	isValid $SECUREDBUILD "${SECURITYLIST[@]}"
	isError $LINENO
	isValid $LOGLEVEL "${LOGLEVELLIST[@]}"
	isError $LINENO
	isValid $CAPABILITY "${CAPABILITYLIST[@]}"
	isError $LINENO
}

function updateToken()
{
	# FIX: this only ever echoed the command, so an existing checkout kept
	# whatever remote it was originally cloned from. Repointing GITUSER at a
	# different org therefore had no effect and the subsequent
	# `git checkout $GITBRANCH` failed on branches that only exist in the new
	# remote. Also guard on the directory existing: on a first run getCode()
	# calls this before the clone.
	if [ -d "$fullPath/.git" ]; then
		( cd "$fullPath" && git remote set-url origin "$GITHUBURL" ) || return 1
	fi
}

function removeExisting()
{
	sleep 2
	rm -rf HE3
}

function getCode()
{
        local fullPath=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER
        local branchname=""
        updateToken
        if [ ! -d "$fullPath" ]; then
                echo "$fullPath doesn't exist, cloning..."
                git clone $GITHUBURL $fullPath
                isError $LINENO
                cd $fullPath
                git checkout $GITBRANCH
                isError $LINENO
        else
                echo "$fullPath exist, updating..."
                cd $fullPath
                git fetch origin
                isError $LINENO
                # FIX: discard the previous build's output before switching.
                # The build modifies tracked files (bootloader.bin, key.json,
                # partition.bin, build_info.h), so `git checkout <otherbranch>`
                # aborted with "local changes would be overwritten" whenever
                # consecutive builds used different branches. The reset/clean
                # below the checkout already discards these -- doing it first
                # just lets the switch happen.
                git reset --hard
                isError $LINENO
                git clean -fd
                isError $LINENO
                git checkout $GITBRANCH
                isError $LINENO
        fi
        if [ "$SHA" == "HEAD" ]; then
                git reset --hard origin/$GITBRANCH
        else
                git reset --hard $SHA
        fi
        isError $LINENO
        git clean -fd
        isError $LINENO
        branchname=$(git rev-parse --abbrev-ref HEAD)
        GITSHA=$(git rev-parse HEAD | cut -c1-8)
        echo "GIT BRANCHNAME=$branchname"
        echo "GIT SHA=$GITSHA"
        sleep 3
        cd $CHECKOUTPATH
}

function useFlashInfo()
{
	echo "Configuring for FLASH=$FLASH..."

	rm $FLASHLD
	rm $FLASHCFG

	if [ "$FLASH" == 2 ]; then
		echo "Copying $FLASHCFG2 as $FLASHCFG"
		cp $FLASHCFG2 $FLASHCFG
		echo "Copying $FLASHLD2 as $FLASHLD"
		cp $FLASHLD2 $FLASHLD

	elif [ "$FLASH" == 4 ]; then
		echo "Copying $FLASHCFG4 as $FLASHCFG"
		cp $FLASHCFG4 $FLASHCFG
		echo "Copying $FLASHLD4 as $FLASHLD"
		cp $FLASHLD4 $FLASHLD
	fi
}

function useTypeInfo()
{
	echo "TODO"
}

function useBoardInfo()
{
	echo "TODO"
}

function useCustomerInfo()
{
	echo "TODO"
}

function genOTAHostingBuild()
{
	if [ "$PLATFORM" == "he3" ]; then
		# HE3_Flash_and_OTA_image_generation_script.py is not present in this
		# tree. The original called it unconditionally and printed
		# "generating hosting build success" regardless of the result, so a
		# missing script looked like a successful stage. Report honestly.
		if [ -f "HE3_Flash_and_OTA_image_generation_script.py" ]; then
			echo "generating hosting build"
			python HE3_Flash_and_OTA_image_generation_script.py
			isError $LINENO
			echo "generating hosting build success"
		else
			echo "SKIP: HE3_Flash_and_OTA_image_generation_script.py not present"
		fi

		if [ -f "HE3_renesas_image_gen.py" ]; then
			echo "generating renesas combined build..."
			python3 HE3_renesas_image_gen.py
			isError $LINENO
		else
			echo "SKIP: HE3_renesas_image_gen.py not present"
		fi

	elif [ "$FLASH" == "8MB" ]; then
		python hoagsOTAHostingImageGeneration_FW_8MB_Havells.py $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/OTA_All.bin $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/OTA_All_8MB.xz.bin
		sleep 2
		python Combine_BLder_Env_hoagsOTAHostingImageGeneration_8MB_Havells.py --inputFw $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/OTA_All.bin --inputEnv dummyEnv.bin --inputBootL $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/km4_boot_all.bin --outputImage $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/OTA_All_withBootloader_8MB.xz.bin
	else
		python hoagsOTAHostingImageGeneration.py $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/OTA_All.bin $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/OTA_All_4MB.xz.bin $MODEL
		sleep 2
		python Combine_BLder_Env_hoagsOTAHostingImageGeneration.py --inputFw $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/OTA_All.bin --inputEnv dummyEnv.bin --inputBootL $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/km4_boot_all.bin --outputImage $CHECKOUTPARENTFOLDER/$SRCIMAGEPATH/OTA_All_withBootloader_4MB.xz.bin
	fi
}

function generateSecuredKeys()
{
	if [ "$SECUREDBUILD" == "1" ]; then
		if [ "$CUSTOMERNAME" == "HAVELLS_HANDTUNED" ] || [ "$CUSTOMERNAME" == "HAVELLS_AC" ]; then
			cp -rf $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/$SECURITYHAVELLSFOLDER/* $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/../

		elif [ "$CUSTOMERNAME" == "VIRTUALFOREST_AC" ]; then
			cp -rf $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/$SECURITYVIRTUALFORESTFOLDER/* $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/../

		elif [ "$CUSTOMERNAME" == "VERSADEVICES_SUPERFAN_IOT" ]; then
			cp -rf $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/$SECURITYVERSADEVICESFOLDER/* $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/../

		elif [ "$CUSTOMERNAME" == "LIVPURE_CHIMNEY" ] || [ "$CUSTOMERNAME" == "LIVPURE_CHIMNEY_SMOKE" ]; then
			cp -rf $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/$SECURITYLIVPUREFOLDER/* $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/../

		elif [ "$CUSTOMERNAME" == "POLYCAB_FAN" ]; then
			cp -rf $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/$SECURITYPOLYCABFOLDER/* $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/../

		elif [ "$CUSTOMERNAME" == "AMBER_AIRCOOLER" ]; then
			cp -rf $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/$SECURITYAMBERFOLDER/* $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/../

		elif [ "$CUSTOMERNAME" == "UNISEMI" ] || [ "$CUSTOMERNAME" == "RR_KABLES" ] || [ "$CUSTOMERNAME" == "ATOMBERG_FAN" ] || [ "$CUSTOMERNAME" == "MOBILISE_FMHUB" ] || [ "$CUSTOMERNAME" == "AMBER_AC" ] || [ "$CUSTOMERNAME" == "VGUARD_NEW_FAN" ] || [ "$CUSTOMERNAME" == "OMNI_AC" ] || [ "$CUSTOMERNAME" == "INDCOOL_AC" ] || [ "$CUSTOMERNAME" == "HOAGS_DEMO_LIGHT" ] ||
[ "$CUSTOMERNAME" == "LIVPURE_PURIFIER" ] || [ "$CUSTOMERNAME" == "SYMPHONY_AIRCOOLER" ] || [ "$CUSTOMERNAME" == "CRUISE_AC" ] || [ "$CUSTOMERNAME" == "ORIENT" ] || [ "$CUSTOMERNAME" == "BLDC_CHINESE" ] || [ "$CUSTOMERNAME" == "DIY" ] || [ "$CUSTOMERNAME" == "HELIUM_AC" ] || [ "$CUSTOMERNAME" == "NEOTERRA_AC" ] || [ "$CUSTOMERNAME" == "INDCOOL_MEGMEET" ]; then
			echo "Using POC keys"
			cp -rf $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/$SECURITYPOCFOLDER/* $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SECUREDPATH/../

		else
			echo "Security keys not yet generated for $CUSTOMERNAME, aborting build!!!"
			exit
		fi
	fi
}

function build()
{
        local makePath=$CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$MAKEPATH
        cd $makePath
        make clean
        sleep 2
        chmod -R +x $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/sdk-ameba-v7.1d/tools/ 2>/dev/null
        find $CHECKOUTPATH/$CHECKOUTPARENTFOLDER -name "*.linux" -exec chmod +x {} \; 2>/dev/null
        make
        if [[ $? -ne 0 ]]; then
                echo "Build Error!!!, aborting..."
                exit 1
        fi
        cd $CHECKOUTPATH
}

function versioning()
{
	local version=$PLATFORM.$TYPE
	local minor=""

	if [ "$TYPE" == "prod" ]; then
		if [ "$PLATFORM" == "he3" ]; then
			# FIX: previously this branch never checked PLATFORM and always
			# wrote .IMG_VER_MAJOR/.IMG_VER_MINOR — the wrong JSON keys for
			# the he3 manifest schema (which uses .FWHS.header.serial), and
			# it never touched version.h at all. Now mirrors dev/test.
			minor=$(<$PRODVERSIONFILE)
			jq ".FWHS.header.serial = $minor" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			sed -i "1c\\#define VERSION_MAJOR $MAJORPROD" $VERSION_HEADER_FILE
			stt="#define VERSION_MINOR $minor"
			echo Current Path $PWD
			echo $VERSION_HEADER_FILE
			sed -i "2c\\$stt" $VERSION_HEADER_FILE
			version=$version.$minor

			if [ "$SECURESOC" == "1" ]; then
				jq ".PARTAB.header.enc = true" $MANIFESTFILEPATH_BOOTLOADER > .output.json && mv .output.json  $MANIFESTFILEPATH_BOOTLOADER
				jq ".BOOT.header.enc = true" $MANIFESTFILEPATH_BOOTLOADER > .output.json && mv .output.json  $MANIFESTFILEPATH_BOOTLOADER
				sed -i 's/BOOTLOADER secure_bit=0/BOOTLOADER secure_bit=1/g' $MAKEFILE_PATH
				sed -i 's/PARTITIONTABLE secure_bit=0/PARTITIONTABLE secure_bit=1/g' $MAKEFILE_PATH
				sed -i 's/FIRMWARE secure_bit=0/FIRMWARE secure_bit=1/g' $MAKEFILE_PATH
			fi
		else
			minor=$(<$PRODVERSIONFILE)
			jq ".IMG_VER_MAJOR = $MAJORPROD" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			jq ".IMG_VER_MINOR = $minor" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			version=$version.$minor
		fi

	elif [ "$TYPE" == "dev" ]; then
		if [ "$PLATFORM" == "he3" ]; then
			minor=$(<$DEVVERSIONFILE)
			jq ".FWHS.header.serial = $minor" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			sed -i "1c\\#define VERSION_MAJOR $MAJORDEV" $VERSION_HEADER_FILE
			stt="#define VERSION_MINOR $minor"
			echo Current Path $PWD
			echo $VERSION_HEADER_FILE
			sed -i "2c\\$stt" $VERSION_HEADER_FILE
			version=$version.$minor

			if [ "$SECURESOC" == "1" ]; then
				jq ".PARTAB.header.enc = true" $MANIFESTFILEPATH_BOOTLOADER > .output.json && mv .output.json  $MANIFESTFILEPATH_BOOTLOADER
				jq ".BOOT.header.enc = true" $MANIFESTFILEPATH_BOOTLOADER > .output.json && mv .output.json  $MANIFESTFILEPATH_BOOTLOADER
				sed -i 's/BOOTLOADER secure_bit=0/BOOTLOADER secure_bit=1/g' $MAKEFILE_PATH
				sed -i 's/PARTITIONTABLE secure_bit=0/PARTITIONTABLE secure_bit=1/g' $MAKEFILE_PATH
				sed -i 's/FIRMWARE secure_bit=0/FIRMWARE secure_bit=1/g' $MAKEFILE_PATH
			fi

		else
			minor=$(<$DEVVERSIONFILE)
			jq ".IMG_VER_MAJOR = $MAJORDEV" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			jq ".IMG_VER_MINOR = $minor" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			version=$version.$minor
		fi

	elif [ "$TYPE" == "test" ]; then
		if [ "$PLATFORM" == "he3" ]; then
			minor=$(<$TESTVERSIONFILE)
			jq ".FWHS.header.serial = $minor" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			# FIX: this line was missing entirely — VERSION_MAJOR was never
			# written for test builds, so it kept whatever value the last
			# build (dev or otherwise) had left behind instead of being 1.
			sed -i "1c\\#define VERSION_MAJOR $MAJORTEST" $VERSION_HEADER_FILE
			stt="#define VERSION_MINOR $minor"
			echo Current Path $PWD
			echo $VERSION_HEADER_FILE
			sed -i "2c\\$stt" $VERSION_HEADER_FILE
			version=$version.$minor

			if [ "$SECURESOC" == "1" ]; then
				jq ".PARTAB.header.enc = true" $MANIFESTFILEPATH_BOOTLOADER > .output.json && mv .output.json  $MANIFESTFILEPATH_BOOTLOADER
				jq ".BOOT.header.enc = true" $MANIFESTFILEPATH_BOOTLOADER > .output.json && mv .output.json  $MANIFESTFILEPATH_BOOTLOADER
				sed -i 's/BOOTLOADER secure_bit=0/BOOTLOADER secure_bit=1/g' $MAKEFILE_PATH
				sed -i 's/PARTITIONTABLE secure_bit=0/PARTITIONTABLE secure_bit=1/g' $MAKEFILE_PATH
				sed -i 's/FIRMWARE secure_bit=0/FIRMWARE secure_bit=1/g' $MAKEFILE_PATH
			fi
		else
			minor=$(<$TESTVERSIONFILE)
			jq ".IMG_VER_MAJOR = $MAJORTEST" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			jq ".IMG_VER_MINOR = $minor" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			version=$version.$minor
		fi

	elif [ "$TYPE" == "test-ota" ]; then
		minor=9999
		if [ "$PLATFORM" == "he3" ]; then
			jq ".FWHS.header.serial = $minor" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			# FIX: same gap as the test branch — major was never written.
			sed -i "1c\\#define VERSION_MAJOR $MAJORTEST" $VERSION_HEADER_FILE
			stt="#define VERSION_MINOR $minor"
			echo Current Path $PWD
			echo $VERSION_HEADER_FILE
			sed -i "2c\\$stt" $VERSION_HEADER_FILE
			version=$version.$minor
		else
			jq ".IMG_VER_MAJOR = $MAJORTEST" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			jq ".IMG_VER_MINOR = $minor" $MANIFESTFILEPATH > .output.json && mv .output.json $MANIFESTFILEPATH
			version=$version.$minor
		fi
	fi

	# The OTA manifest previously tracked its own independent counter
	# (e.g. 1.419 -> 1.420) with no relation to the actual firmware
	# version written into version.h. This derives the real
	# MAJOR.MINOR from the same constants versioning() just used, so
	# build.sh can hand it to update_manifest.py and the manifest
	# reflects the real firmware version instead of an unrelated counter.
	case "$TYPE" in
		dev) MAJORMINORVERSION="$MAJORDEV.$minor" ;;
		test|test-ota) MAJORMINORVERSION="$MAJORTEST.$minor" ;;
		prod) MAJORMINORVERSION="$MAJORPROD.$minor" ;;
	esac

	VERSION=$version
	echo "Build Version=$version"
	echo "Manifest Version (major.minor)=$MAJORMINORVERSION"
}

function copyBuild()
{
	local epoch=$(date +"%s")
	cd $CHECKOUTPATH/$CHECKOUTPARENTFOLDER && GITSHA=$(git rev-parse HEAD | cut -c1-8)
	BUILDNAME=$VERSION-$GITSHA-$epoch.zip

	if [ "$PLATFORM" == "he2" ]; then
		cd $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SRCIMAGEPATH && cd ../ && zip -r $TARGETIMAGEPATH/$BUILDNAME bin

	elif [ "$PLATFORM" == "he3" ]; then
		cd $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SRCIMAGEPATH && cd ../ && zip -r $TARGETIMAGEPATH/$BUILDNAME application_is

	else
		cd $CHECKOUTPATH/$CHECKOUTPARENTFOLDER/$SRCIMAGEPATH && cd ../ && zip -r $TARGETIMAGEPATH/$BUILDNAME image
	fi

	cd $CHECKOUTPATH
}

function copyToolChain()
{
	cp -rf /home/build/build-scripts/patches/vsdk /home/build/build-scripts/Platform/Entry/HE1/RTL872xEA_v10.1c_beta/project/realtek_amebaLite_va0_example/GCC-RELEASE/project_kr4/toolchain/
	cp -rf /home/build/build-scripts/patches/asdk /home/build/build-scripts/Platform/Entry/HE1/RTL872xEA_v10.1c_beta/project/realtek_amebaLite_va0_example/GCC-RELEASE/project_km4/toolchain/
}

function incrementVersionFile()
{
	if [ "$TYPE" == "prod" ]; then
		number=$(<$PRODVERSIONFILE)
		number=$(($number+1))
		echo $number > $PRODVERSIONFILE

	elif [ "$TYPE" == "dev" ]; then
		number=$(<$DEVVERSIONFILE)
		number=$(($number+1))
		echo $number > $DEVVERSIONFILE

	elif [ "$TYPE" == "test" ]; then
		number=$(<$TESTVERSIONFILE)
		number=$(($number+1))
		echo $number > $TESTVERSIONFILE
	fi
}

function postBuild()
{
	echo "Post Build operation here"
}
