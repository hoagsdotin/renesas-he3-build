@'
pipeline {
    agent { label 'renesas-build' }

    parameters {
        choice(
            name: 'PLATFORM',
            choices: ['BOTH', 'RA', 'RL78'],
            description: 'Which firmware to build'
        )
        choice(
            name: 'BUILD_TYPE',
            choices: ['dev', 'test', 'mp'],
            description: 'Build type passed to hoags-build --build-type'
        )
        booleanParam(
            name: 'RUN_HE3',
            defaultValue: true,
            description: 'If true, run full "he3" (push + HE3 build). If false, only "firmware".'
        )
        booleanParam(
            name: 'CI_MODE',
            defaultValue: false,
            description: 'Pass --ci (S3 upload + OTA manifest rewrite).'
        )
    }

    options {
        disableConcurrentBuilds()
        timestamps()
        timeout(time: 90, unit: 'MINUTES')
    }

    triggers {
        githubPush()
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Doctor') {
            steps {
                sh './new_build_system/hoags-build doctor'
            }
        }

        stage('Build') {
            steps {
                script {
                    def platformArg = [
                        'BOTH': '',
                        'RA':   'lotier',
                        'RL78': 'eterna',
                    ][params.PLATFORM]

                    def cmd = params.RUN_HE3 ? 'he3' : 'firmware'
                    def ciFlag = params.CI_MODE ? '--ci' : ''

                    sh """
                        cd new_build_system
                        ./hoags-build ${cmd} ${platformArg} --build-type ${params.BUILD_TYPE} ${ciFlag}
                    """
                }
            }
        }
    }

    post {
        success {
            echo "Build succeeded: platform=${params.PLATFORM} type=${params.BUILD_TYPE} he3=${params.RUN_HE3} ci=${params.CI_MODE}"
        }
        failure {
            echo "Build failed — check the 'Build' stage log above."
        }
        always {
            archiveArtifacts artifacts: '**/*.log', allowEmptyArchive: true
        }
    }
}
'@ | Set-Content -Path Jenkinsfile -Encoding UTF8
